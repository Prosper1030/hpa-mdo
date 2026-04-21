import json
import shutil
import subprocess
from pathlib import Path

import pytest

import hpa_meshing.adapters.gmsh_backend as gmsh_backend_module
from hpa_meshing.adapters.gmsh_backend import (
    _probe_discrete_classify_angles,
    _collect_plc_error_probe,
    _configure_mesh_field,
    _extract_overlap_surface_details,
    _resolve_exact_overlap_surface_pair,
    _run_surface_repair_fallback,
    _should_attempt_surface_repair_fallback,
    apply_recipe,
)
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


class _FakePlcMeshModule:
    def __init__(self) -> None:
        self.last_entity_error = [(2, 16), (1, 44)]
        self.last_node_error = [101, 202]
        self.node_lookup = {
            101: ([1.0, 2.0, 3.0], [], 2, 16),
            202: ([1.0, 2.0, 3.0], [], 1, 44),
        }

    def getLastEntityError(self):
        return list(self.last_entity_error)

    def getLastNodeError(self):
        return list(self.last_node_error)

    def getNode(self, tag):
        return self.node_lookup[int(tag)]


class _FakePlcModel:
    def __init__(self) -> None:
        self.mesh = _FakePlcMeshModule()

    def getEntitiesInBoundingBox(self, xmin, ymin, zmin, xmax, ymax, zmax, dim=-1):
        assert xmax >= xmin
        assert ymax >= ymin
        assert zmax >= zmin
        if dim == -1:
            return [(2, 16), (1, 44), (2, 19)]
        return [(dim, 16)]

    def getBoundingBox(self, dim, tag):
        return (0.9, 1.9, 2.9, 1.1, 2.1, 3.1)


class _FakePlcGmsh:
    def __init__(self) -> None:
        self.model = _FakePlcModel()


class _FakeOverlapMeshModule:
    def __init__(self) -> None:
        self.removed_elements: list[tuple[int, int, list[int]]] = []
        self.reclassify_calls = 0
        self.remove_duplicate_node_calls = 0

    def removeElements(self, dim, tag, element_tags):
        self.removed_elements.append((int(dim), int(tag), list(element_tags)))

    def reclassifyNodes(self):
        self.reclassify_calls += 1

    def removeDuplicateNodes(self):
        self.remove_duplicate_node_calls += 1


class _FakeOverlapModel:
    def __init__(self) -> None:
        self.mesh = _FakeOverlapMeshModule()
        self._bboxes = {
            (2, 48): (0.1939135563076736, -15.47845725851829, 0.5697698172955429, 0.876824496018745, -13.48606786258499, 0.7147903383577676),
            (2, 39): (0.0, -15.47845725851829, -0.06803674310717782, 1.302328642723384, 15.47845725851962, 0.7147903383577676),
        }

    def getBoundingBox(self, dim, tag):
        return self._bboxes[(int(dim), int(tag))]


class _FakeOverlapGmsh:
    def __init__(self) -> None:
        self.model = _FakeOverlapModel()


def test_collect_plc_error_probe_includes_point_localization_and_last_errors(tmp_path: Path):
    probe = _collect_plc_error_probe(
        _FakePlcGmsh(),
        error_text="PLC Error: A segment and a facet intersect at point",
        logger_messages=[
            "Info    : Found problem near point (1.0, 2.0, 3.0)",
            "Error   : PLC Error: A segment and a facet intersect at point",
        ],
        surface_mesh_path=tmp_path / "surface_mesh_2d.msh",
        mesh_algorithm_3d=1,
    )

    assert probe["status"] == "captured"
    assert probe["mesh_algorithm_3d"] == 1
    assert probe["intersection_points"][0]["coordinates"] == [1.0, 2.0, 3.0]
    assert probe["last_entity_error_dim_tags"] == [{"dim": 2, "tag": 16}, {"dim": 1, "tag": 44}]
    assert probe["last_node_error_nodes"][0]["tag"] == 101
    assert probe["intersection_point_entity_hits"][0]["entities"][0] == {"dim": 2, "tag": 16}
    assert probe["surface_mesh_artifact"] == str(tmp_path / "surface_mesh_2d.msh")


def test_collect_plc_error_probe_falls_back_to_last_node_coordinates_when_logger_has_no_xyz():
    probe = _collect_plc_error_probe(
        _FakePlcGmsh(),
        error_text="PLC Error: A segment and a facet intersect at point",
        logger_messages=["Error   : PLC Error: A segment and a facet intersect at point"],
        surface_mesh_path=None,
        mesh_algorithm_3d=10,
    )

    assert probe["status"] == "captured"
    assert probe["mesh_algorithm_3d"] == 10
    assert probe["intersection_points"][0]["source"] == "last_node_error"
    assert probe["intersection_points"][0]["coordinates"] == [1.0, 2.0, 3.0]


def test_should_attempt_surface_repair_fallback_matches_known_boundary_recovery_signatures():
    assert _should_attempt_surface_repair_fallback(
        "PLC Error: A segment and a facet intersect at point",
        [],
    )
    assert _should_attempt_surface_repair_fallback(
        "Invalid boundary mesh (overlapping facets) on surface 39 surface 40",
        [],
    )
    assert _should_attempt_surface_repair_fallback(
        "3D mesher failed",
        ["Info    : failed to recover constrained lines/triangles"],
    )
    assert _should_attempt_surface_repair_fallback(
        "3D mesher failed",
        ["Info    : Found two exactly self-intersecting facets"],
    )
    assert _should_attempt_surface_repair_fallback(
        "3D mesher failed",
        ["Info    : Found two nearly self-intersecting facets"],
    )
    assert not _should_attempt_surface_repair_fallback(
        "OpenCASCADE import failed",
        ["Info    : STEP parser aborted"],
    )


def test_extract_overlap_surface_details_reports_surface_pair_bboxes_and_facet_tags():
    details = _extract_overlap_surface_details(
        _FakePlcGmsh(),
        "Invalid boundary mesh (overlapping facets) on surface 48 surface 39",
        [
            "Info    : Found two exactly self-intersecting facets (dihedral angle  0.00000E+00).",
            "Info    :   1st: [80, 83, 82] #48",
            "Info    :   2nd: [80, 83, 18] #39",
            "Error   : Invalid boundary mesh (overlapping facets) on surface 48 surface 39",
        ],
    )

    assert details["surface_tags"] == [48, 39]
    assert details["facet_tags_from_logger"] == [48, 39]
    assert details["self_intersection_kind"] == "exact"
    assert details["surface_bboxes"][0]["tag"] == 48
    assert details["surface_bboxes"][1]["tag"] == 39


def test_resolve_exact_overlap_surface_pair_removes_smaller_surface_mesh():
    gmsh = _FakeOverlapGmsh()

    resolved = _resolve_exact_overlap_surface_pair(
        gmsh,
        {
            "surface_tags": [48, 39],
            "self_intersection_kind": "exact",
            "surface_bboxes": [
                {"dim": 2, "tag": 48, "bbox": gmsh.model.getBoundingBox(2, 48)},
                {"dim": 2, "tag": 39, "bbox": gmsh.model.getBoundingBox(2, 39)},
            ],
        },
    )

    assert resolved["status"] == "resolved"
    assert resolved["removed_surface_tag"] == 48
    assert gmsh.model.mesh.removed_elements == [(2, 48, [])]
    assert gmsh.model.mesh.reclassify_calls == 1
    assert gmsh.model.mesh.remove_duplicate_node_calls == 1


def test_run_surface_repair_fallback_rebuilds_boundary_groups_and_writes_reports(tmp_path: Path):
    normalized = _write_occ_box_step(tmp_path, "box_for_surface_repair.step")
    source = tmp_path / "demo.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    provider_result = _provider_result(source, normalized)
    config = MeshJobConfig(
        component="aircraft_assembly",
        geometry=source,
        out_dir=tmp_path / "baseline_out",
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

    baseline = apply_recipe(recipe, handle, config)
    assert baseline["status"] == "success"

    baseline_metadata = json.loads(Path(baseline["artifacts"]["mesh_metadata"]).read_text(encoding="utf-8"))
    surface_mesh_path = Path(baseline["artifacts"]["surface_mesh_2d"])
    retry_mesh_path = tmp_path / "surface_repair_retry.msh"
    cleanup_report_path = tmp_path / "surface_cleanup_report.json"
    discrete_reparam_report_path = tmp_path / "discrete_reparam_report.json"
    retry_metadata_path = tmp_path / "retry_mesh_metadata.json"

    fallback = _run_surface_repair_fallback(
        surface_mesh_path=surface_mesh_path,
        bounds=baseline_metadata["farfield"]["bounds"],
        mesh_path=retry_mesh_path,
        cleanup_report_path=cleanup_report_path,
        discrete_reparam_report_path=discrete_reparam_report_path,
        retry_metadata_path=retry_metadata_path,
        mesh_algorithm_2d=5,
        mesh_algorithm_3d=1,
    )

    assert fallback["status"] == "success"
    assert fallback["route_stage"] == "surface_repair_fallback"
    assert retry_mesh_path.exists()
    assert cleanup_report_path.exists()
    assert discrete_reparam_report_path.exists()
    assert retry_metadata_path.exists()
    assert fallback["marker_summary"]["aircraft"]["exists"] is True
    assert fallback["marker_summary"]["farfield"]["exists"] is True
    assert fallback["mesh_stats"]["volume_element_count"] > 0

    cleanup_report = json.loads(cleanup_report_path.read_text(encoding="utf-8"))
    assert cleanup_report["status"] == "completed"
    assert cleanup_report["duplicate_nodes_removed"] >= 0

    discrete_report = json.loads(discrete_reparam_report_path.read_text(encoding="utf-8"))
    assert discrete_report["status"] == "completed"
    assert discrete_report["aircraft_surface_count"] > 0
    assert discrete_report["farfield_surface_count"] > 0

    retry_metadata = json.loads(retry_metadata_path.read_text(encoding="utf-8"))
    assert retry_metadata["status"] == "success"
    assert retry_metadata["mesh"]["volume_element_count"] > 0


def test_run_surface_repair_fallback_fails_when_retry_mesh_has_no_volume_elements(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    normalized = _write_occ_box_step(tmp_path, "box_for_surface_repair_no_volume.step")
    source = tmp_path / "demo.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    provider_result = _provider_result(source, normalized)
    config = MeshJobConfig(
        component="aircraft_assembly",
        geometry=source,
        out_dir=tmp_path / "baseline_out",
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

    baseline = apply_recipe(recipe, handle, config)
    assert baseline["status"] == "success"

    surface_mesh_path = Path(baseline["artifacts"]["surface_mesh_2d"])
    retry_mesh_path = tmp_path / "surface_repair_retry_no_volume.msh"
    cleanup_report_path = tmp_path / "surface_cleanup_report.json"
    discrete_reparam_report_path = tmp_path / "discrete_reparam_report.json"
    retry_metadata_path = tmp_path / "retry_mesh_metadata.json"

    real_mesh_stats = gmsh_backend_module._mesh_stats

    def _fake_mesh_stats(gmsh):
        stats = real_mesh_stats(gmsh)
        stats["volume_element_count"] = 0
        stats["volume_element_type_counts"] = {}
        return stats

    monkeypatch.setattr(gmsh_backend_module, "_mesh_stats", _fake_mesh_stats)

    fallback = _run_surface_repair_fallback(
        surface_mesh_path=surface_mesh_path,
        bounds=json.loads(Path(baseline["artifacts"]["mesh_metadata"]).read_text(encoding="utf-8"))["farfield"]["bounds"],
        mesh_path=retry_mesh_path,
        cleanup_report_path=cleanup_report_path,
        discrete_reparam_report_path=discrete_reparam_report_path,
        retry_metadata_path=retry_metadata_path,
        mesh_algorithm_2d=5,
        mesh_algorithm_3d=1,
    )

    assert fallback["status"] == "failed"
    assert "did not generate any volume elements" in fallback["error"]
    retry_metadata = json.loads(retry_metadata_path.read_text(encoding="utf-8"))
    assert retry_metadata["status"] == "failed"
    assert "did not generate any volume elements" in retry_metadata["error"]


def test_probe_discrete_classify_angles_reports_results_for_surface_mesh(tmp_path: Path):
    normalized = _write_occ_box_step(tmp_path, "box_for_classify_probe.step")
    source = tmp_path / "demo.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    provider_result = _provider_result(source, normalized)
    config = MeshJobConfig(
        component="aircraft_assembly",
        geometry=source,
        out_dir=tmp_path / "baseline_out",
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

    baseline = apply_recipe(recipe, handle, config)
    assert baseline["status"] == "success"

    surface_mesh_path = Path(baseline["artifacts"]["surface_mesh_2d"])
    probe_path = tmp_path / "classify_angle_probe.json"
    probe = _probe_discrete_classify_angles(
        surface_mesh_path=surface_mesh_path,
        probe_path=probe_path,
        angle_degrees=[40.0, 20.0],
        mesh_algorithm_2d=5,
        mesh_algorithm_3d=1,
    )

    assert probe_path.exists()
    assert probe["status"] == "completed"
    assert len(probe["results"]) == 2
    assert all(item["status"] in {"success", "failed"} for item in probe["results"])


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


def test_apply_recipe_heals_clean_esp_rebuilt_geometry_before_external_flow_meshing(tmp_path: Path):
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
    assert metadata["body"]["healing"]["attempted"] is True
    assert metadata["surface_topology"]["aircraft_connectivity_before_meshing"]["free_curve_count"] == 0
    assert metadata["surface_mesh"]["cleanup_actions"]["removed_duplicate_facets"] == 0


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


def test_apply_recipe_generates_occ_mesh_for_thin_sheet_surface_route(tmp_path: Path):
    normalized = _write_occ_box_step(tmp_path, "wing_box.step")
    source = tmp_path / "demo.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    provider_result = GeometryProviderResult(
        provider="esp_rebuilt",
        provider_stage="experimental",
        status="materialized",
        geometry_source="esp_rebuilt",
        source_path=source,
        normalized_geometry_path=normalized,
        geometry_family_hint="thin_sheet_lifting_surface",
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
        component="main_wing",
        geometry=source,
        out_dir=tmp_path / "out",
        geometry_source="esp_rebuilt",
        geometry_family="thin_sheet_lifting_surface",
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
        declared_family="thin_sheet_lifting_surface",
        component="main_wing",
        provider="esp_rebuilt",
        provider_status="materialized",
        provider_result=provider_result,
    )
    classification = GeometryClassification(
        geometry_source="esp_rebuilt",
        geometry_provider="esp_rebuilt",
        declared_family="thin_sheet_lifting_surface",
        inferred_family=None,
        geometry_family="thin_sheet_lifting_surface",
        provenance="test",
        notes=[],
    )
    recipe = build_recipe(handle, classification, config)

    result = apply_recipe(recipe, handle, config)

    assert recipe.meshing_route == "gmsh_thin_sheet_surface"
    assert result["status"] == "success"
    assert Path(result["artifacts"]["mesh"]).exists()
    metadata = json.loads(Path(result["artifacts"]["mesh_metadata"]).read_text(encoding="utf-8"))
    assert metadata["geometry_family"] == "thin_sheet_lifting_surface"
    assert metadata["surface_mesh"]["duplicate_facets_after_cleanup"]["duplicate_facet_count"] == 0


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
