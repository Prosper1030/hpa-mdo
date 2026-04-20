import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hpa_meshing.adapters.gmsh_backend import apply_recipe
from hpa_meshing.mesh.recipes import build_recipe
from hpa_meshing.schema import (
    GeometryClassification,
    GeometryHandle,
    GeometryProviderResult,
    GeometryTopologyMetadata,
    MeshJobConfig,
)


def _write_occ_box_step(tmp_path: Path, name: str = "box.step") -> Path:
    gmsh_bin = shutil.which("gmsh")
    if gmsh_bin is None:
        pytest.skip("gmsh CLI not available")

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


def _write_occ_box_step_with_dims(
    tmp_path: Path,
    x_length: float,
    y_length: float,
    z_length: float,
    name: str = "box.step",
) -> Path:
    gmsh_bin = shutil.which("gmsh")
    if gmsh_bin is None:
        pytest.skip("gmsh CLI not available")

    tmp_path.mkdir(parents=True, exist_ok=True)
    geo_path = tmp_path / f"{name}.geo"
    step_path = tmp_path / name
    geo_path.write_text(
        'SetFactory("OpenCASCADE");\n'
        f"Box(1) = {{0, 0, 0, {x_length}, {y_length}, {z_length}}};\n",
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


def _provider_result(source: Path, normalized: Path) -> GeometryProviderResult:
    return GeometryProviderResult(
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


def test_apply_recipe_generates_occ_mesh_artifacts_and_marker_summary(tmp_path: Path):
    normalized = _write_occ_box_step(tmp_path)
    source = tmp_path / "demo.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    provider_result = _provider_result(source, normalized)
    config = MeshJobConfig(
        component="aircraft_assembly",
        geometry=source,
        out_dir=tmp_path / "out",
        geometry_source="provider_generated",
        geometry_family="thin_sheet_aircraft_assembly",
        geometry_provider="openvsp_surface_intersection",
    )
    handle = GeometryHandle(
        source_path=source,
        path=normalized,
        exists=True,
        suffix=normalized.suffix.lower(),
        loader="provider:openvsp_surface_intersection",
        geometry_source="provider_generated",
        declared_family="thin_sheet_aircraft_assembly",
        component="aircraft_assembly",
        provider="openvsp_surface_intersection",
        provider_status="materialized",
        provider_result=provider_result,
    )
    classification = GeometryClassification(
        geometry_source="provider_generated",
        geometry_provider="openvsp_surface_intersection",
        declared_family="thin_sheet_aircraft_assembly",
        inferred_family=None,
        geometry_family="thin_sheet_aircraft_assembly",
        provenance="test",
        notes=[],
    )
    recipe = build_recipe(handle, classification, config)

    result = apply_recipe(recipe, handle, config)

    assert result["status"] == "success"
    assert result["route_stage"] == "baseline"
    assert result["mesh_format"] == "msh"
    assert Path(result["artifacts"]["mesh"]).exists()
    assert Path(result["artifacts"]["mesh_metadata"]).exists()
    assert Path(result["artifacts"]["marker_summary"]).exists()
    assert result["marker_summary"]["aircraft"]["exists"] is True
    assert result["marker_summary"]["farfield"]["exists"] is True
    assert result["mesh_stats"]["node_count"] > 0
    assert result["mesh_stats"]["element_count"] > 0
    assert result["mesh_stats"]["volume_element_count"] > 0

    metadata = json.loads(Path(result["artifacts"]["mesh_metadata"]).read_text(encoding="utf-8"))
    assert metadata["meshing_route"] == "gmsh_thin_sheet_aircraft_assembly"
    assert metadata["geometry"]["normalized_path"] == str(normalized)
    assert metadata["marker_summary"]["aircraft"]["exists"] is True
    assert metadata["marker_summary"]["farfield"]["exists"] is True


def test_apply_recipe_rescales_imported_geometry_to_provider_units(tmp_path: Path):
    normalized = _write_occ_box_step_with_dims(tmp_path, 1000, 200, 100, "scaled_box.step")
    source = tmp_path / "demo.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
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
                "x_max": 1.0,
                "y_min": 0.0,
                "y_max": 0.2,
                "z_min": 0.0,
                "z_max": 0.1,
            },
            import_bounds={
                "x_min": 0.0,
                "x_max": 1000.0,
                "y_min": 0.0,
                "y_max": 200.0,
                "z_min": 0.0,
                "z_max": 100.0,
            },
            import_scale_to_units=0.001,
            backend_rescale_required=True,
        ),
        provenance={"analysis": "SurfaceIntersection"},
    )
    config = MeshJobConfig(
        component="aircraft_assembly",
        geometry=source,
        out_dir=tmp_path / "out",
        geometry_source="provider_generated",
        geometry_family="thin_sheet_aircraft_assembly",
        geometry_provider="openvsp_surface_intersection",
    )
    handle = GeometryHandle(
        source_path=source,
        path=normalized,
        exists=True,
        suffix=normalized.suffix.lower(),
        loader="provider:openvsp_surface_intersection",
        geometry_source="provider_generated",
        declared_family="thin_sheet_aircraft_assembly",
        component="aircraft_assembly",
        provider="openvsp_surface_intersection",
        provider_status="materialized",
        provider_result=provider_result,
    )
    classification = GeometryClassification(
        geometry_source="provider_generated",
        geometry_provider="openvsp_surface_intersection",
        declared_family="thin_sheet_aircraft_assembly",
        inferred_family=None,
        geometry_family="thin_sheet_aircraft_assembly",
        provenance="test",
        notes=[],
    )
    recipe = build_recipe(handle, classification, config)

    result = apply_recipe(recipe, handle, config)

    assert result["status"] == "success"
    metadata = json.loads(Path(result["artifacts"]["mesh_metadata"]).read_text(encoding="utf-8"))
    assert metadata["units"] == "m"
    assert metadata["body"]["bounds"]["x_max"] == pytest.approx(1.0, rel=1e-3)
    assert metadata["body"]["bounds"]["y_max"] == pytest.approx(0.2, rel=1e-3)
    assert metadata["body"]["bounds"]["z_max"] == pytest.approx(0.1, rel=1e-3)
    assert metadata["mesh_field"]["characteristic_length"] == pytest.approx(1.0, rel=1e-3)


def test_apply_recipe_writes_mesh_handoff_contract(tmp_path: Path):
    normalized = _write_occ_box_step(tmp_path)
    source = tmp_path / "demo.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    provider_result = _provider_result(source, normalized)
    config = MeshJobConfig(
        component="aircraft_assembly",
        geometry=source,
        out_dir=tmp_path / "out",
        geometry_source="provider_generated",
        geometry_family="thin_sheet_aircraft_assembly",
        geometry_provider="openvsp_surface_intersection",
    )
    handle = GeometryHandle(
        source_path=source,
        path=normalized,
        exists=True,
        suffix=normalized.suffix.lower(),
        loader="provider:openvsp_surface_intersection",
        geometry_source="provider_generated",
        declared_family="thin_sheet_aircraft_assembly",
        component="aircraft_assembly",
        provider="openvsp_surface_intersection",
        provider_status="materialized",
        provider_result=provider_result,
    )
    classification = GeometryClassification(
        geometry_source="provider_generated",
        geometry_provider="openvsp_surface_intersection",
        declared_family="thin_sheet_aircraft_assembly",
        inferred_family=None,
        geometry_family="thin_sheet_aircraft_assembly",
        provenance="test",
        notes=[],
    )
    recipe = build_recipe(handle, classification, config)

    result = apply_recipe(recipe, handle, config)

    metadata = json.loads(Path(result["artifacts"]["mesh_metadata"]).read_text(encoding="utf-8"))
    marker_summary = json.loads(Path(result["artifacts"]["marker_summary"]).read_text(encoding="utf-8"))

    assert metadata["contract"] == "mesh_handoff.v1"
    assert metadata["artifacts"]["mesh"] == result["artifacts"]["mesh"]
    assert metadata["artifacts"]["marker_summary"] == result["artifacts"]["marker_summary"]
    assert metadata["geometry_provider"] == "openvsp_surface_intersection"
    assert metadata["physical_groups"]["aircraft"]["exists"] is True
    assert metadata["marker_summary"] == marker_summary
    assert metadata["provenance"]["route_provenance"] == "geometry_family_registry"
