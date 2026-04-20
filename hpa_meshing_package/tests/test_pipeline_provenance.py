import json
from pathlib import Path
import shutil
import subprocess

import pytest

from hpa_meshing.geometry import loader as geometry_loader
from hpa_meshing.pipeline import run_job
from hpa_meshing.schema import (
    GeometryProviderResult,
    GeometryTopologyMetadata,
    MeshJobConfig,
    SU2RuntimeConfig,
)


def _write_occ_box_step(tmp_path: Path, name: str = "box.step") -> Path:
    gmsh_bin = shutil.which("gmsh")
    assert gmsh_bin is not None, "gmsh CLI not available"

    tmp_path.mkdir(parents=True, exist_ok=True)
    geo_path = tmp_path / "box.geo"
    step_path = tmp_path / name
    geo_path.write_text(
        'SetFactory("OpenCASCADE");\n'
        "Box(1) = {0, 0, 0, 1, 0.2, 0.1};\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [gmsh_bin, str(geo_path), "-0", "-o", str(step_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert step_path.exists()
    return step_path


def test_run_job_reports_geometry_family_and_route_provenance(tmp_path: Path):
    geometry = tmp_path / "wing.step"
    geometry.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")

    config = MeshJobConfig(
        component="main_wing",
        geometry=geometry,
        out_dir=tmp_path / "out",
        geometry_source="esp_rebuilt",
    )

    result = run_job(config)

    assert result["status"] == "success"
    assert result["geometry_source"] == "esp_rebuilt"
    assert result["geometry_family"] == "thin_sheet_lifting_surface"
    assert result["classification"]["provenance"] == "component_family_default"
    assert result["dispatch"]["meshing_route"] == "gmsh_thin_sheet_surface"
    assert result["dispatch"]["route_provenance"] == "geometry_family_registry"
    assert result["dispatch"]["backend_capability"] == "sheet_lifting_surface_meshing"

    report = json.loads((config.out_dir / "report.json").read_text(encoding="utf-8"))
    assert report["geometry_family"] == "thin_sheet_lifting_surface"
    assert report["dispatch"]["backend_capability"] == "sheet_lifting_surface_meshing"


def test_run_job_reports_provider_provenance_and_normalized_geometry(
    tmp_path: Path,
    monkeypatch,
):
    source = tmp_path / "assembly.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    provider_dir = tmp_path / "provider-artifacts"
    normalized = _write_occ_box_step(provider_dir, "normalized.stp")
    topology_report = provider_dir / "topology.json"
    topology_report.write_text('{"volume_count": 3}', encoding="utf-8")

    provider_result = GeometryProviderResult(
        provider="openvsp_surface_intersection",
        provider_stage="v1",
        status="materialized",
        geometry_source="provider_generated",
        source_path=source,
        normalized_geometry_path=normalized,
        geometry_family_hint="thin_sheet_aircraft_assembly",
        topology=GeometryTopologyMetadata(
            representation="brep_trimmed_step",
            source_kind="vsp3",
            units="m",
            body_count=3,
            surface_count=38,
            volume_count=3,
            labels_present=True,
        ),
        artifacts={"topology_report": topology_report},
        provenance={"analysis": "SurfaceIntersection"},
    )

    monkeypatch.setattr(
        geometry_loader,
        "materialize_geometry_with_provider",
        lambda path, config: provider_result,
    )

    config = MeshJobConfig(
        component="aircraft_assembly",
        geometry=source,
        out_dir=tmp_path / "out",
        geometry_provider="openvsp_surface_intersection",
    )

    result = run_job(config)

    assert result["status"] == "success"
    assert result["geometry"] == str(config.geometry)
    assert result["normalized_geometry"] == str(normalized)
    assert result["geometry_source"] == "provider_generated"
    assert result["geometry_provider"] == "openvsp_surface_intersection"
    assert result["classification"]["provenance"] == "provider.geometry_family_hint"
    assert result["dispatch"]["meshing_route"] == "gmsh_thin_sheet_aircraft_assembly"
    assert result["provider"]["status"] == "materialized"
    assert result["provider"]["artifacts"]["topology_report"] == str(topology_report)

    report = json.loads((config.out_dir / "report.json").read_text(encoding="utf-8"))
    assert report["provider"]["topology"]["volume_count"] == 3


def test_run_job_reports_mesh_artifacts_marker_summary_and_counts(
    tmp_path: Path,
    monkeypatch,
):
    source = tmp_path / "assembly.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    normalized = _write_occ_box_step(tmp_path, "assembly_trimmed.stp")

    provider_result = GeometryProviderResult(
        provider="openvsp_surface_intersection",
        provider_stage="v1",
        status="materialized",
        geometry_source="provider_generated",
        source_path=source,
        normalized_geometry_path=normalized,
        geometry_family_hint="thin_sheet_aircraft_assembly",
        topology=GeometryTopologyMetadata(
            representation="brep_trimmed_step",
            source_kind="stp",
            units="m",
            body_count=1,
            surface_count=6,
            volume_count=1,
            labels_present=False,
            label_schema="preserve_component_labels",
        ),
        provenance={"analysis": "SurfaceIntersection"},
    )

    monkeypatch.setattr(
        geometry_loader,
        "materialize_geometry_with_provider",
        lambda path, config: provider_result,
    )

    config = MeshJobConfig(
        component="aircraft_assembly",
        geometry=source,
        out_dir=tmp_path / "out",
        geometry_provider="openvsp_surface_intersection",
    )

    result = run_job(config)

    assert result["status"] == "success"
    assert result["dispatch"]["meshing_route"] == "gmsh_thin_sheet_aircraft_assembly"
    assert result["mesh"]["route_stage"] == "baseline"
    assert result["mesh"]["mesh_format"] == "msh"
    assert Path(result["mesh"]["mesh_artifact"]).exists()
    assert Path(result["mesh"]["metadata_path"]).exists()
    assert Path(result["mesh"]["marker_summary_path"]).exists()
    assert result["mesh"]["marker_summary"]["aircraft"]["exists"] is True
    assert result["mesh"]["marker_summary"]["farfield"]["exists"] is True
    assert result["mesh"]["node_count"] > 0
    assert result["mesh"]["element_count"] > 0
    assert result["mesh"]["volume_element_count"] > 0

    report = json.loads((config.out_dir / "report.json").read_text(encoding="utf-8"))
    assert report["mesh"]["marker_summary"]["aircraft"]["exists"] is True
    assert report["mesh"]["marker_summary"]["farfield"]["exists"] is True
    assert Path(report["mesh"]["mesh_artifact"]).exists()


def test_run_job_reports_unit_normalized_mesh_bounds(tmp_path: Path, monkeypatch):
    source = tmp_path / "assembly.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    normalized = _write_occ_box_step(tmp_path, "assembly_scaled.stp")

    provider_result = GeometryProviderResult(
        provider="openvsp_surface_intersection",
        provider_stage="v1",
        status="materialized",
        geometry_source="provider_generated",
        source_path=source,
        normalized_geometry_path=normalized,
        geometry_family_hint="thin_sheet_aircraft_assembly",
        topology=GeometryTopologyMetadata(
            representation="brep_trimmed_step",
            source_kind="stp",
            units="m",
            body_count=1,
            surface_count=6,
            volume_count=1,
            labels_present=False,
            label_schema="preserve_component_labels",
            bounds={
                "x_min": 0.0,
                "x_max": 0.001,
                "y_min": 0.0,
                "y_max": 0.0002,
                "z_min": 0.0,
                "z_max": 0.0001,
            },
            import_bounds={
                "x_min": 0.0,
                "x_max": 1.0,
                "y_min": 0.0,
                "y_max": 0.2,
                "z_min": 0.0,
                "z_max": 0.1,
            },
            import_scale_to_units=0.001,
            backend_rescale_required=True,
        ),
        provenance={"analysis": "SurfaceIntersection"},
    )

    monkeypatch.setattr(
        geometry_loader,
        "materialize_geometry_with_provider",
        lambda path, config: provider_result,
    )

    config = MeshJobConfig(
        component="aircraft_assembly",
        geometry=source,
        out_dir=tmp_path / "out",
        geometry_provider="openvsp_surface_intersection",
    )

    result = run_job(config)

    assert result["provider"]["topology"]["units"] == "m"
    assert result["provider"]["topology"]["bounds"]["x_max"] == pytest.approx(0.001, rel=1e-3)
    assert result["mesh"]["units"] == "m"
    assert result["mesh"]["body_bounds"]["x_max"] == pytest.approx(0.001, rel=1e-3)
    assert result["mesh"]["farfield_bounds"]["x_max"] > result["mesh"]["body_bounds"]["x_max"]

    report = json.loads((config.out_dir / "report.json").read_text(encoding="utf-8"))
    assert report["mesh"]["units"] == "m"
    assert report["mesh"]["body_bounds"]["x_max"] == pytest.approx(0.001, rel=1e-3)


def test_run_job_surfaces_mesh_handoff_contract(tmp_path: Path, monkeypatch):
    source = tmp_path / "assembly.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    normalized = _write_occ_box_step(tmp_path, "assembly_handoff.stp")

    provider_result = GeometryProviderResult(
        provider="openvsp_surface_intersection",
        provider_stage="v1",
        status="materialized",
        geometry_source="provider_generated",
        source_path=source,
        normalized_geometry_path=normalized,
        geometry_family_hint="thin_sheet_aircraft_assembly",
        topology=GeometryTopologyMetadata(
            representation="brep_trimmed_step",
            source_kind="stp",
            units="m",
            body_count=1,
            surface_count=6,
            volume_count=1,
            labels_present=False,
            label_schema="preserve_component_labels",
        ),
        provenance={"analysis": "SurfaceIntersection"},
    )

    monkeypatch.setattr(
        geometry_loader,
        "materialize_geometry_with_provider",
        lambda path, config: provider_result,
    )

    config = MeshJobConfig(
        component="aircraft_assembly",
        geometry=source,
        out_dir=tmp_path / "out",
        geometry_provider="openvsp_surface_intersection",
    )

    result = run_job(config)

    assert result["mesh"]["contract"] == "mesh_handoff.v1"
    assert result["mesh"]["backend_capability"] == "sheet_aircraft_assembly_meshing"
    assert result["mesh"]["geometry_family"] == "thin_sheet_aircraft_assembly"
    assert result["mesh"]["physical_groups"]["farfield"]["exists"] is True
    assert result["mesh"]["provenance"]["route_provenance"] == "geometry_family_registry"
    assert result["mesh"]["provenance"]["provider"]["provider"] == "openvsp_surface_intersection"

    report = json.loads((config.out_dir / "report.json").read_text(encoding="utf-8"))
    assert report["mesh"]["contract"] == "mesh_handoff.v1"
    assert report["mesh"]["provenance"]["provider"]["provider_stage"] == "v1"


def test_run_job_fails_when_su2_baseline_fails(tmp_path: Path, monkeypatch):
    from hpa_meshing import pipeline as mesh_pipeline

    geometry = tmp_path / "assembly.vsp3"
    geometry.write_text("<vsp3/>", encoding="utf-8")
    normalized = _write_occ_box_step(tmp_path / "provider", "normalized.stp")
    provider_result = GeometryProviderResult(
        provider="openvsp_surface_intersection",
        provider_stage="v1",
        status="materialized",
        geometry_source="provider_generated",
        source_path=geometry,
        normalized_geometry_path=normalized,
        geometry_family_hint="thin_sheet_aircraft_assembly",
        topology=GeometryTopologyMetadata(
            representation="brep_trimmed_step",
            source_kind="stp",
            units="m",
            body_count=1,
            surface_count=6,
            volume_count=1,
            labels_present=False,
            label_schema="preserve_component_labels",
        ),
        provenance={"analysis": "SurfaceIntersection"},
    )

    monkeypatch.setattr(
        mesh_pipeline,
        "run_baseline_case",
        lambda mesh_handoff, runtime, case_root, source_root=None: {
            "contract": "su2_handoff.v1",
            "run_status": "failed",
            "failure_code": "solver_not_found",
            "error": "SU2_CFD not found on PATH",
            "solver_command": "SU2_CFD su2_runtime.cfg",
            "runtime_cfg_path": str(Path(case_root) / runtime.case_name / "su2_runtime.cfg"),
            "history_path": None,
            "final_coefficients": {"cl": None, "cd": None, "cm": None},
            "provenance": {"source_contract": "mesh_handoff.v1"},
        },
    )
    monkeypatch.setattr(
        geometry_loader,
        "materialize_geometry_with_provider",
        lambda path, config: provider_result,
    )

    config = MeshJobConfig(
        component="aircraft_assembly",
        geometry=geometry,
        out_dir=tmp_path / "out",
        geometry_provider="openvsp_surface_intersection",
        su2=SU2RuntimeConfig(enabled=True),
    )

    result = run_job(config)

    assert result["status"] == "failed"
    assert result["failure_code"] == "solver_not_found"
    assert result["su2"]["run_status"] == "failed"

    report = json.loads((config.out_dir / "report.json").read_text(encoding="utf-8"))
    assert report["failure_code"] == "solver_not_found"
    assert report["su2"]["error"] == "SU2_CFD not found on PATH"


def test_run_job_reports_su2_reference_and_force_surface_gates(tmp_path: Path, monkeypatch):
    from hpa_meshing import pipeline as mesh_pipeline

    geometry = tmp_path / "assembly.vsp3"
    geometry.write_text("<vsp3/>", encoding="utf-8")
    normalized = _write_occ_box_step(tmp_path / "provider", "normalized.stp")
    provider_result = GeometryProviderResult(
        provider="openvsp_surface_intersection",
        provider_stage="v1",
        status="materialized",
        geometry_source="provider_generated",
        source_path=geometry,
        normalized_geometry_path=normalized,
        geometry_family_hint="thin_sheet_aircraft_assembly",
        topology=GeometryTopologyMetadata(
            representation="brep_trimmed_step",
            source_kind="stp",
            units="m",
            body_count=3,
            surface_count=38,
            volume_count=3,
            labels_present=True,
            label_schema="preserve_component_labels",
        ),
        provenance={"analysis": "SurfaceIntersection"},
    )

    monkeypatch.setattr(
        mesh_pipeline,
        "run_baseline_case",
        lambda mesh_handoff, runtime, case_root, source_root=None: {
            "contract": "su2_handoff.v1",
            "run_status": "completed",
            "solver_command": "SU2_CFD su2_runtime.cfg",
            "runtime_cfg_path": str(Path(case_root) / runtime.case_name / "su2_runtime.cfg"),
            "history_path": str(Path(case_root) / runtime.case_name / "history.csv"),
            "case_output_paths": {
                "case_dir": str(Path(case_root) / runtime.case_name),
                "contract_path": str(Path(case_root) / runtime.case_name / "su2_handoff.json"),
            },
            "final_coefficients": {"cl": 0.18, "cd": 0.03, "cm": -0.007, "cm_axis": "CMy"},
            "reference_geometry": {
                "ref_area": 35.175,
                "ref_length": 1.0425,
                "ref_origin_moment": {"x": 0.0, "y": 0.0, "z": 0.0},
                "area_provenance": {
                    "source_category": "geometry_derived",
                    "method": "openvsp_reference_wing.sref",
                    "confidence": "high",
                },
                "length_provenance": {
                    "source_category": "geometry_derived",
                    "method": "openvsp_reference_wing.cref",
                    "confidence": "high",
                },
                "moment_origin_provenance": {
                    "source_category": "geometry_derived",
                    "method": "openvsp_vspaero_settings.cg",
                    "confidence": "medium",
                },
                "gate_status": "pass",
                "confidence": "high",
                "warnings": [],
                "notes": [],
            },
            "force_surface_provenance": {
                "gate_status": "pass",
                "confidence": "medium",
                "source_kind": "mesh_physical_group",
                "wall_marker": "aircraft",
                "monitoring_markers": ["aircraft"],
                "plotting_markers": ["aircraft"],
                "euler_markers": ["aircraft"],
                "source_groups": [
                    {
                        "marker_name": "aircraft",
                        "physical_name": "aircraft",
                        "physical_tag": 2,
                        "dimension": 2,
                        "entity_count": 38,
                        "element_count": 180,
                    }
                ],
                "primary_group": {
                    "marker_name": "aircraft",
                    "physical_name": "aircraft",
                    "physical_tag": 2,
                    "dimension": 2,
                    "entity_count": 38,
                    "element_count": 180,
                },
                "matches_wall_marker": True,
                "matches_entire_aircraft_wall": True,
                "scope": "whole_aircraft_wall",
                "body_count": 3,
                "component_labels_present_in_geometry": True,
                "component_label_schema": "preserve_component_labels",
                "component_provenance": "geometry_labels_present_but_not_mapped",
                "warnings": [],
                "notes": [],
            },
            "provenance_gates": {
                "overall_status": "pass",
                "reference_quantities": {"status": "pass", "confidence": "high", "warnings": [], "notes": []},
                "force_surface": {"status": "pass", "confidence": "medium", "warnings": [], "notes": []},
            },
            "provenance": {"source_contract": "mesh_handoff.v1"},
            "notes": ["baseline test stub"],
        },
    )
    monkeypatch.setattr(
        geometry_loader,
        "materialize_geometry_with_provider",
        lambda path, config: provider_result,
    )

    config = MeshJobConfig(
        component="aircraft_assembly",
        geometry=geometry,
        out_dir=tmp_path / "out",
        geometry_provider="openvsp_surface_intersection",
        su2=SU2RuntimeConfig(enabled=True),
    )

    result = run_job(config)

    assert result["status"] == "success"
    assert result["su2"]["reference_geometry"]["gate_status"] == "pass"
    assert result["su2"]["force_surface_provenance"]["scope"] == "whole_aircraft_wall"
    assert result["su2"]["provenance_gates"]["reference_quantities"]["status"] == "pass"

    report = json.loads((config.out_dir / "report.json").read_text(encoding="utf-8"))
    assert report["su2"]["reference_geometry"]["area_provenance"]["method"] == "openvsp_reference_wing.sref"
    assert report["su2"]["force_surface_provenance"]["component_provenance"] == "geometry_labels_present_but_not_mapped"
    assert report["su2"]["provenance_gates"]["overall_status"] == "pass"
