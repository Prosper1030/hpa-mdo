import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hpa_meshing.adapters.gmsh_backend import _configure_mesh_field, apply_recipe
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
        provenance={
            "analysis": "SurfaceIntersection",
            "reference_geometry": {
                "ref_area": 1.0,
                "ref_length": 1.0,
                "ref_origin_moment": {"x": 0.25, "y": 0.0, "z": 0.0},
                "area_method": "test.reference_area",
                "length_method": "test.reference_length",
                "moment_method": "test.reference_origin",
                "warnings": [],
            },
        },
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
        global_min_size=0.5,
        global_max_size=2.0,
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


def test_apply_recipe_skips_occ_heal_for_clean_esp_rebuilt_geometry(tmp_path: Path):
    normalized = _write_occ_box_step(tmp_path, "clean_box.step")
    source = tmp_path / "demo.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    provider_result = GeometryProviderResult(
        provider="esp_rebuilt",
        provider_stage="experimental",
        status="materialized",
        geometry_source="esp_rebuilt",
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
            labels_present=True,
            label_schema="preserve_component_labels",
            normalization={
                "applied": True,
                "final_analysis": {
                    "touching_groups": [],
                    "duplicate_interface_face_pair_count": 0,
                    "internal_cap_face_count": 0,
                },
            },
        ),
        provenance={
            "normalization": {
                "applied": True,
            },
            "reference_geometry": {
                "ref_area": 1.0,
                "ref_length": 1.0,
                "ref_origin_moment": {"x": 0.25, "y": 0.0, "z": 0.0},
                "area_method": "test.reference_area",
                "length_method": "test.reference_length",
                "moment_method": "test.reference_origin",
                "warnings": [],
            },
        },
    )
    config = MeshJobConfig(
        component="aircraft_assembly",
        geometry=source,
        out_dir=tmp_path / "out",
        geometry_source="esp_rebuilt",
        geometry_family="thin_sheet_aircraft_assembly",
        geometry_provider="esp_rebuilt",
        global_min_size=0.5,
        global_max_size=2.0,
    )
    handle = GeometryHandle(
        source_path=source,
        path=normalized,
        exists=True,
        suffix=normalized.suffix.lower(),
        loader="provider:esp_rebuilt",
        geometry_source="esp_rebuilt",
        declared_family="thin_sheet_aircraft_assembly",
        component="aircraft_assembly",
        provider="esp_rebuilt",
        provider_status="materialized",
        provider_result=provider_result,
    )
    classification = GeometryClassification(
        geometry_source="esp_rebuilt",
        geometry_provider="esp_rebuilt",
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
    assert metadata["body"]["healing"]["attempted"] is False
    assert metadata["body"]["healing"]["reason"] == "skipped_for_provider_declared_clean_external_geometry"


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
        provenance={
            "analysis": "SurfaceIntersection",
            "reference_geometry": {
                "ref_area": 1.0,
                "ref_length": 1.0,
                "ref_origin_moment": {"x": 0.25, "y": 0.0, "z": 0.0},
                "area_method": "test.reference_area",
                "length_method": "test.reference_length",
                "moment_method": "test.reference_origin",
                "warnings": [],
            },
        },
    )
    config = MeshJobConfig(
        component="aircraft_assembly",
        geometry=source,
        out_dir=tmp_path / "out",
        geometry_source="provider_generated",
        geometry_family="thin_sheet_aircraft_assembly",
        geometry_provider="openvsp_surface_intersection",
        global_min_size=0.5,
        global_max_size=2.0,
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
    assert metadata["mesh_field"]["characteristic_length_policy"] == "reference_length"
    assert metadata["mesh_field"]["reference_length"] == pytest.approx(1.0, rel=1e-3)


class _FakeFieldApi:
    def __init__(self) -> None:
        self.added: list[str] = []
        self.numbers: dict[tuple[int, str], list[float]] = {}
        self.number_values: dict[tuple[int, str], float] = {}
        self.background: int | None = None

    def add(self, kind: str) -> int:
        self.added.append(kind)
        return len(self.added)

    def setNumbers(self, field: int, name: str, values: list[int]) -> None:
        self.numbers[(field, name)] = [float(value) for value in values]

    def setNumber(self, field: int, name: str, value: float) -> None:
        self.number_values[(field, name)] = float(value)

    def setAsBackgroundMesh(self, field: int) -> None:
        self.background = field


class _FakeMeshApi:
    def __init__(self) -> None:
        self.field = _FakeFieldApi()


class _FakeModelApi:
    def __init__(self) -> None:
        self.mesh = _FakeMeshApi()


class _FakeOptionApi:
    def __init__(self) -> None:
        self.values: dict[str, float] = {}

    def setNumber(self, name: str, value: float) -> None:
        self.values[name] = float(value)


class _FakeGmsh:
    def __init__(self) -> None:
        self.model = _FakeModelApi()
        self.option = _FakeOptionApi()


def test_configure_mesh_field_uses_reference_length_surface_and_edge_policy(tmp_path: Path):
    config = MeshJobConfig(
        component="aircraft_assembly",
        geometry=tmp_path / "demo.vsp3",
        out_dir=tmp_path / "out",
        geometry_source="provider_generated",
        geometry_family="thin_sheet_aircraft_assembly",
        geometry_provider="openvsp_surface_intersection",
    )
    gmsh = _FakeGmsh()

    info = _configure_mesh_field(
        gmsh,
        [101, 102],
        [201, 202, 203],
        1.0425,
        config,
    )

    assert gmsh.model.mesh.field.added == ["Distance", "Threshold", "Distance", "Threshold", "Min"]
    assert gmsh.model.mesh.field.numbers[(1, "FacesList")] == [101.0, 102.0]
    assert gmsh.model.mesh.field.numbers[(3, "CurvesList")] == [201.0, 202.0, 203.0]
    assert gmsh.model.mesh.field.numbers[(5, "FieldsList")] == [2.0, 4.0]
    assert gmsh.model.mesh.field.background == 5
    assert info["characteristic_length_policy"] == "reference_length"
    assert info["reference_length"] == pytest.approx(1.0425)
    assert info["surface_target_nodes_per_reference_length"] == 128
    assert info["near_body_size"] == pytest.approx(1.0425 / 128.0)
    assert info["edge_size"] == pytest.approx(1.0425 / 256.0)
    assert info["farfield_size"] == pytest.approx(1.0425 * 4.0)
    assert info["distance_min"] == pytest.approx(0.0)
    assert info["distance_max"] == pytest.approx(1.0425 * 0.25)
    assert info["edge_distance_max"] == pytest.approx(1.0425 * 0.05)
    assert gmsh.option.values["Mesh.MeshSizeMin"] == pytest.approx(1.0425 / 256.0)
    assert gmsh.option.values["Mesh.MeshSizeMax"] == pytest.approx(1.0425 * 4.0)
    assert gmsh.option.values["Mesh.MeshSizeFromPoints"] == 0.0
    assert gmsh.option.values["Mesh.MeshSizeFromCurvature"] == 0.0
    assert gmsh.option.values["Mesh.MeshSizeExtendFromBoundary"] == 0.0
    assert gmsh.option.values["Mesh.Algorithm"] == 6.0
    assert gmsh.option.values["Mesh.Algorithm3D"] == 1.0


def test_apply_recipe_scales_mesh_field_transition_with_requested_sizes(tmp_path: Path):
    normalized = _write_occ_box_step(tmp_path)
    source = tmp_path / "demo.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    provider_result = _provider_result(source, normalized)
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
    coarse_config = MeshJobConfig(
        component="aircraft_assembly",
        geometry=source,
        out_dir=tmp_path / "coarse_out",
        geometry_source="provider_generated",
        geometry_family="thin_sheet_aircraft_assembly",
        geometry_provider="openvsp_surface_intersection",
        global_min_size=0.5,
        global_max_size=2.0,
    )
    fine_config = MeshJobConfig(
        component="aircraft_assembly",
        geometry=source,
        out_dir=tmp_path / "fine_out",
        geometry_source="provider_generated",
        geometry_family="thin_sheet_aircraft_assembly",
        geometry_provider="openvsp_surface_intersection",
        global_min_size=0.3,
        global_max_size=1.5,
    )
    recipe = build_recipe(handle, classification, coarse_config)

    coarse_result = apply_recipe(recipe, handle, coarse_config)
    fine_result = apply_recipe(recipe, handle, fine_config)

    coarse_metadata = json.loads(Path(coarse_result["artifacts"]["mesh_metadata"]).read_text(encoding="utf-8"))
    fine_metadata = json.loads(Path(fine_result["artifacts"]["mesh_metadata"]).read_text(encoding="utf-8"))

    assert coarse_result["status"] == "success"
    assert fine_result["status"] == "success"
    assert fine_metadata["mesh_field"]["near_body_size"] < coarse_metadata["mesh_field"]["near_body_size"]
    assert fine_metadata["mesh_field"]["edge_size"] < coarse_metadata["mesh_field"]["edge_size"]
    assert fine_metadata["mesh_field"]["farfield_size"] < coarse_metadata["mesh_field"]["farfield_size"]
    assert fine_metadata["mesh_field"]["distance_max"] < coarse_metadata["mesh_field"]["distance_max"]
    assert fine_metadata["mesh_field"]["edge_distance_max"] < coarse_metadata["mesh_field"]["edge_distance_max"]
    assert fine_metadata["body"]["healing"]["attempted"] is True
    assert coarse_metadata["body"]["healing"]["attempted"] is True


def test_apply_recipe_rejects_boundary_layer_on_current_occ_tetra_route(tmp_path: Path):
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
        boundary_layer={
            "enabled": True,
            "first_layer_height": 1.0e-4,
            "total_thickness": 0.01,
            "growth_rate": 1.2,
            "n_layers": 12,
        },
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

    assert result["status"] == "failed"
    assert "boundary layer" in result["error"].lower()
    assert "not implemented" in result["error"].lower()


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
        global_min_size=0.5,
        global_max_size=2.0,
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
