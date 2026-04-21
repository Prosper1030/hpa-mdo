import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

import hpa_meshing.adapters.gmsh_backend as gmsh_backend_module
from hpa_meshing.adapters.gmsh_backend import (
    _probe_discrete_classify_angles,
    _collect_plc_error_probe,
    _collect_surface_patch_diagnostics,
    _configure_mesh_field,
    _extract_last_meshing_curve,
    _extract_last_meshing_surface,
    _extract_overlap_surface_details,
    _resolve_coarse_first_tetra_profile,
    _resolve_exact_overlap_surface_pair,
    _resolve_mesh_field_defaults,
    _run_mesh2d_with_watchdog,
    _run_mesh3d_with_watchdog,
    _run_surface_repair_fallback,
    _should_probe_discrete_classify_angles,
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


class _FakeWatchdogLogger:
    def __init__(self, messages: list[str]) -> None:
        self._messages = messages

    def get(self):
        return list(self._messages)


class _FakeWatchdogMeshModule:
    def __init__(self, sleep_seconds: float) -> None:
        self.sleep_seconds = sleep_seconds
        self.calls: list[int] = []

    def generate(self, dim: int) -> None:
        self.calls.append(int(dim))
        time.sleep(self.sleep_seconds)


class _FakeWatchdogModel:
    def __init__(self, sleep_seconds: float) -> None:
        self.mesh = _FakeWatchdogMeshModule(sleep_seconds)


class _FakeWatchdogGmsh:
    def __init__(self, *, sleep_seconds: float, logger_messages: list[str]) -> None:
        self.model = _FakeWatchdogModel(sleep_seconds)
        self.logger = _FakeWatchdogLogger(logger_messages)


class _FakeSurfaceDiagOcc:
    def __init__(self, mass_lookup: dict[tuple[int, int], float]) -> None:
        self._mass_lookup = mass_lookup

    def getMass(self, dim: int, tag: int) -> float:
        return self._mass_lookup[(int(dim), int(tag))]


class _FakeSurfaceDiagModel:
    def __init__(
        self,
        bbox_lookup: dict[tuple[int, int], tuple[float, float, float, float, float, float]],
        boundary_lookup: dict[int, list[int]],
        mass_lookup: dict[tuple[int, int], float],
    ) -> None:
        self._bbox_lookup = bbox_lookup
        self._boundary_lookup = boundary_lookup
        self.occ = _FakeSurfaceDiagOcc(mass_lookup)

    def getBoundingBox(self, dim: int, tag: int):
        return self._bbox_lookup[(int(dim), int(tag))]

    def getBoundary(self, dim_tags, oriented=False, recursive=False):
        assert oriented is False
        assert recursive is False
        dim, tag = dim_tags[0]
        assert int(dim) == 2
        return [(1, curve_tag) for curve_tag in self._boundary_lookup[int(tag)]]


class _FakeSurfaceDiagGmsh:
    def __init__(
        self,
        bbox_lookup: dict[tuple[int, int], tuple[float, float, float, float, float, float]],
        boundary_lookup: dict[int, list[int]],
        mass_lookup: dict[tuple[int, int], float],
    ) -> None:
        self.model = _FakeSurfaceDiagModel(bbox_lookup, boundary_lookup, mass_lookup)


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


def test_extract_last_meshing_surface_returns_last_surface_tag_and_message():
    result = _extract_last_meshing_surface(
        [
            "Info    : Meshing surface 40 (Discrete surface, Frontal-Delaunay)",
            "Info    : Meshing surface 41 (Discrete surface, Frontal-Delaunay)",
            "Progress: Meshing 2D...",
            "Info    : Meshing surface 57 (Discrete surface, MeshAdapt)",
        ]
    )

    assert result is not None
    assert result["surface_tag"] == 57
    assert "MeshAdapt" in result["message"]


def test_extract_last_meshing_curve_returns_last_curve_tag_and_message():
    result = _extract_last_meshing_curve(
        [
            "Info    : Meshing curve 40 (Discrete curve)",
            "Info    : Meshing curve 41 (TrimmedCurve)",
            "Progress: Meshing 1D...",
            "Info    : Meshing curve 57 (Line)",
        ]
    )

    assert result is not None
    assert result["curve_tag"] == 57
    assert "Line" in result["message"]


def test_run_mesh2d_with_watchdog_writes_timeout_artifact(tmp_path: Path):
    gmsh = _FakeWatchdogGmsh(
        sleep_seconds=0.05,
        logger_messages=[
            "Info    : Meshing curve 44 (TrimmedCurve)",
            "Info    : Meshing 2D...",
            "Info    : Meshing surface 45 (Discrete surface, Frontal-Delaunay)",
        ],
    )
    watchdog_path = tmp_path / "mesh2d_watchdog.json"
    sample_path = tmp_path / "mesh2d_watchdog_sample.txt"

    def _fake_sample_runner(pid: int, sample_seconds: int, output_path: Path):
        output_path.write_text(f"sample pid={pid} seconds={sample_seconds}\n", encoding="utf-8")
        return {
            "returncode": 0,
            "stdout_tail": "",
            "stderr_tail": "sample ok",
        }

    payload = _run_mesh2d_with_watchdog(
        gmsh,
        watchdog_path=watchdog_path,
        sample_path=sample_path,
        timeout_seconds=0.01,
        sample_seconds=1,
        sample_runner=_fake_sample_runner,
        surface_patch_lookup={
            45: {
                "tag": 45,
                "area": 0.003,
                "family_hints": ["short_curve_candidate", "high_aspect_strip_candidate"],
            }
        },
    )

    assert gmsh.model.mesh.calls == [2]
    assert payload["status"] == "completed_after_timeout"
    assert payload["meshing_stage_at_timeout"] == "meshing_2d"
    assert payload["last_meshing_curve_tag"] == 44
    assert payload["last_meshing_surface_tag"] == 45
    assert payload["sample"]["returncode"] == 0
    assert payload["last_meshing_surface_record"]["tag"] == 45
    assert watchdog_path.exists()
    assert sample_path.exists()

    persisted = json.loads(watchdog_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "completed_after_timeout"
    assert persisted["last_meshing_curve_tag"] == 44
    assert persisted["last_meshing_surface_tag"] == 45


def test_run_mesh3d_with_watchdog_writes_timeout_artifact(tmp_path: Path):
    gmsh = _FakeWatchdogGmsh(
        sleep_seconds=0.05,
        logger_messages=[
            "Info    : Meshing 3D...",
            "Info    : 3D Meshing 1 volume with 1 connected component",
            "Info    : Tetrahedrizing 128 nodes...",
        ],
    )
    watchdog_path = tmp_path / "mesh3d_watchdog.json"
    sample_path = tmp_path / "mesh3d_watchdog_sample.txt"

    def _fake_sample_runner(pid: int, sample_seconds: int, output_path: Path):
        output_path.write_text(f"sample pid={pid} seconds={sample_seconds}\n", encoding="utf-8")
        return {
            "returncode": 0,
            "stdout_tail": "",
            "stderr_tail": "sample ok",
        }

    payload, error = _run_mesh3d_with_watchdog(
        gmsh,
        watchdog_path=watchdog_path,
        sample_path=sample_path,
        timeout_seconds=0.01,
        sample_seconds=1,
        mesh_algorithm_3d=1,
        sample_runner=_fake_sample_runner,
        pre_mesh_stats={
            "mesh_dim": 2,
            "node_count": 128,
            "element_count": 256,
            "surface_element_count": 240,
            "volume_element_count": 0,
        },
    )

    assert error is None
    assert gmsh.model.mesh.calls == [3]
    assert payload["status"] == "completed_after_timeout"
    assert payload["meshing_stage_at_timeout"] == "meshing_3d"
    assert payload["mesh_algorithm_3d"] == 1
    assert payload["tetrahedrizing_node_count"] == 128
    assert payload["connected_component_count"] == 1
    assert payload["volume_count"] == 1
    assert payload["sample"]["returncode"] == 0
    assert payload["pre_mesh_stats"]["mesh_dim"] == 2
    assert watchdog_path.exists()
    assert sample_path.exists()

    persisted = json.loads(watchdog_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "completed_after_timeout"
    assert persisted["tetrahedrizing_node_count"] == 128


def test_collect_surface_patch_diagnostics_ranks_short_curve_strip_candidates():
    bbox_lookup = {
        (2, 11): (0.95, 13.5, 0.28, 1.10, 16.5, 0.50),
        (2, 12): (0.10, 0.0, -0.05, 0.95, 13.5, 0.75),
        (1, 101): (0.95, 13.5, 0.28, 0.95, 13.5009, 0.28),
        (1, 102): (0.95, 13.5, 0.28, 1.10, 16.5, 0.50),
        (1, 103): (0.95, 13.5, 0.28, 1.10, 16.5, 0.50),
        (1, 104): (1.10, 16.499, 0.50, 1.10, 16.5, 0.50),
        (1, 201): (0.10, 0.0, -0.05, 0.10, 13.5, -0.05),
        (1, 202): (0.10, 0.0, -0.05, 0.95, 13.5, 0.75),
        (1, 203): (0.10, 0.0, -0.05, 0.95, 13.5, 0.75),
        (1, 204): (0.95, 13.5, 0.75, 0.95, 13.5005, 0.75),
    }
    boundary_lookup = {
        11: [101, 102, 103, 104],
        12: [201, 202, 203, 204],
    }
    mass_lookup = {
        (2, 11): 0.0030,
        (2, 12): 0.42,
        (1, 101): 0.0009,
        (1, 102): 3.01,
        (1, 103): 3.01,
        (1, 104): 0.0011,
        (1, 201): 13.5,
        (1, 202): 13.6,
        (1, 203): 13.6,
        (1, 204): 0.0005,
    }
    gmsh = _FakeSurfaceDiagGmsh(bbox_lookup, boundary_lookup, mass_lookup)

    payload = _collect_surface_patch_diagnostics(
        gmsh,
        surface_tags=[11, 12],
        reference_length=1.0425,
        near_body_size=1.0425 / 128.0,
    )

    assert payload["surface_count"] == 2
    assert payload["short_curve_threshold"] > 0.0
    assert payload["tiny_face_area_threshold"] > 0.0
    assert payload["surface_area_distribution"]["min"] == pytest.approx(0.0030)
    assert payload["curve_length_distribution"]["min"] == pytest.approx(0.0005)
    assert payload["family_hint_counts"]["short_curve_candidate"] >= 1
    assert payload["surface_records"][0]["surface_role"] == "aircraft"
    assert payload["suspicious_family_groups"][0]["member_tags"]
    assert payload["smallest_area_surfaces"][0]["tag"] == 11
    assert payload["shortest_curves"][0]["tag"] == 204
    assert payload["suspicious_surfaces"][0]["tag"] == 11
    assert "short_curve_candidate" in payload["suspicious_surfaces"][0]["family_hints"]
    assert "high_aspect_strip_candidate" in payload["suspicious_surfaces"][0]["family_hints"]


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


def test_should_probe_discrete_classify_angles_skips_no_volume_failures():
    assert not _should_probe_discrete_classify_angles(
        {
            "status": "failed",
            "error": "surface-repair fallback returned without exception but did not generate any volume elements",
        },
        surface_mesh_exists=True,
        classify_probe_exists=False,
    )
    assert _should_probe_discrete_classify_angles(
        {
            "status": "failed",
            "error": "Invalid boundary mesh (overlapping facets) on surface 39 surface 40",
        },
        surface_mesh_exists=True,
        classify_probe_exists=False,
    )
    assert not _should_probe_discrete_classify_angles(
        {
            "status": "success",
            "error": None,
        },
        surface_mesh_exists=True,
        classify_probe_exists=False,
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


def test_apply_recipe_marks_mesh_dim_2_route_as_surface_only_probe(tmp_path: Path):
    normalized = _write_occ_box_step(tmp_path, "surface_only_box.step")
    source = tmp_path / "demo.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    provider_result = _provider_result(source, normalized)
    config = MeshJobConfig(
        component="aircraft_assembly",
        geometry=source,
        out_dir=tmp_path / "surface_only_out",
        geometry_source="provider_generated",
        geometry_family="thin_sheet_aircraft_assembly",
        geometry_provider="openvsp_surface_intersection",
        mesh_dim=2,
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

    assert result["status"] == "failed"
    assert result["failure_code"] == "surface_mesh_only_probe"
    assert result["route_stage"] == "surface_mesh_only"
    assert result["mesh_stats"]["mesh_dim"] == 2
    assert result["mesh_stats"]["volume_element_count"] == 0
    assert result["artifacts"]["surface_mesh_2d"] is not None
    assert result.get("mesh_handoff") is None

    metadata = json.loads(Path(result["artifacts"]["mesh_metadata"]).read_text(encoding="utf-8"))
    assert metadata["status"] == "surface_mesh_only"
    assert metadata["failure_code"] == "surface_mesh_only_probe"
    assert metadata["route_stage"] == "surface_mesh_only"
    assert metadata["volume_meshing"]["requested"] is False
    assert metadata["volume_meshing"]["attempted"] is False


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
        self.set_algorithm_calls: list[tuple[int, int, int]] = []

    def setAlgorithm(self, dim: int, tag: int, val: int) -> None:
        self.set_algorithm_calls.append((int(dim), int(tag), int(val)))


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


def test_configure_mesh_field_applies_native_esp_surface_policy_from_patch_diagnostics(tmp_path: Path):
    config = MeshJobConfig(
        component="main_wing",
        geometry=tmp_path / "demo.vsp3",
        out_dir=tmp_path / "out",
        geometry_source="esp_rebuilt",
        geometry_family="thin_sheet_lifting_surface",
        geometry_provider="esp_rebuilt",
    )
    gmsh = _FakeGmsh()
    surface_patch_diagnostics = {
        "surface_records": [
            {
                "tag": 5,
                "surface_role": "aircraft",
                "curve_tags": [105, 205],
                "family_hints": ["short_curve_candidate", "high_aspect_strip_candidate"],
            },
            {
                "tag": 6,
                "surface_role": "aircraft",
                "curve_tags": [106, 206],
                "family_hints": ["short_curve_candidate", "high_aspect_strip_candidate"],
            },
            {
                "tag": 14,
                "surface_role": "aircraft",
                "curve_tags": [114, 214],
                "family_hints": [],
            },
            {
                "tag": 31,
                "surface_role": "aircraft",
                "curve_tags": [131, 231],
                "family_hints": [
                    "short_curve_candidate",
                    "high_aspect_strip_candidate",
                    "span_extreme_candidate",
                ],
            },
            {
                "tag": 32,
                "surface_role": "aircraft",
                "curve_tags": [132, 232],
                "family_hints": [
                    "short_curve_candidate",
                    "high_aspect_strip_candidate",
                    "span_extreme_candidate",
                ],
            },
        ]
    }

    info = _configure_mesh_field(
        gmsh,
        [5, 6, 14, 31, 32],
        [105, 106, 114, 131, 132, 205, 206, 214, 231, 232],
        1.0425,
        config,
        farfield_surface_tags=[33],
        surface_patch_diagnostics=surface_patch_diagnostics,
    )

    assert gmsh.model.mesh.field.added == [
        "Distance",
        "Threshold",
        "Distance",
        "Threshold",
        "Min",
        "Constant",
        "Constant",
        "Constant",
        "Max",
    ]
    assert gmsh.model.mesh.field.numbers[(6, "SurfacesList")] == [31.0, 32.0]
    assert gmsh.model.mesh.field.numbers[(6, "CurvesList")] == [131.0, 132.0, 231.0, 232.0]
    assert gmsh.model.mesh.field.number_values[(6, "VIn")] == pytest.approx(0.03)
    assert gmsh.model.mesh.field.number_values[(6, "VOut")] == pytest.approx(0.0)
    assert gmsh.model.mesh.field.numbers[(7, "SurfacesList")] == [5.0, 6.0]
    assert gmsh.model.mesh.field.number_values[(7, "VIn")] == pytest.approx(0.02)
    assert gmsh.model.mesh.field.numbers[(8, "SurfacesList")] == [33.0]
    assert gmsh.model.mesh.field.number_values[(8, "VIn")] == pytest.approx(1.0425 * 4.0)
    assert gmsh.model.mesh.field.numbers[(9, "FieldsList")] == [5.0, 6.0, 7.0, 8.0]
    assert gmsh.model.mesh.field.background == 9
    assert gmsh.model.mesh.set_algorithm_calls == [
        (2, 31, 1),
        (2, 32, 1),
        (2, 5, 1),
        (2, 6, 1),
        (2, 14, 5),
        (2, 33, 5),
    ]
    assert info["background_field_composition"] == "max_with_local_floors"
    assert info["per_surface_algorithms"] == [
        {
            "name": "suspect_strip_family",
            "algorithm": 1,
            "algorithm_name": "MeshAdapt",
            "surface_tags": [31, 32, 5, 6],
        },
        {
            "name": "aircraft_general_surfaces",
            "algorithm": 5,
            "algorithm_name": "Delaunay",
            "surface_tags": [14],
        },
        {
            "name": "farfield_boundary_surfaces",
            "algorithm": 5,
            "algorithm_name": "Delaunay",
            "surface_tags": [33],
        },
    ]
    assert info["local_size_floors"] == [
        {
            "name": "span_extreme_strip_floor",
            "size": pytest.approx(0.03),
            "surface_tags": [31, 32],
            "curve_tags": [131, 132, 231, 232],
        },
        {
            "name": "suspect_strip_floor",
            "size": pytest.approx(0.02),
            "surface_tags": [5, 6],
            "curve_tags": [105, 106, 205, 206],
        },
        {
            "name": "farfield_surface_floor",
            "size": pytest.approx(1.0425 * 4.0),
            "surface_tags": [33],
            "curve_tags": [],
        },
    ]


def test_coarse_first_tetra_profile_defaults_disabled(tmp_path: Path):
    config = MeshJobConfig(
        component="main_wing",
        geometry=tmp_path / "demo.vsp3",
        out_dir=tmp_path / "out",
    )
    profile = _resolve_coarse_first_tetra_profile(config)
    assert profile["enabled"] is False
    defaults = _resolve_mesh_field_defaults(1.0425, config)
    assert defaults["surface_nodes_per_reference_length"] == pytest.approx(128.0)
    assert defaults["edge_refinement_ratio"] == pytest.approx(0.5)
    assert defaults["near_body_size"] == pytest.approx(1.0425 / 128.0)
    assert defaults["edge_size"] == pytest.approx(1.0425 / 256.0)
    assert defaults["coarse_first_tetra"]["enabled"] is False


def test_coarse_first_tetra_profile_scales_sizes_when_enabled(tmp_path: Path):
    config = MeshJobConfig(
        component="main_wing",
        geometry=tmp_path / "demo.vsp3",
        out_dir=tmp_path / "out",
        metadata={"coarse_first_tetra_enabled": True},
    )
    profile = _resolve_coarse_first_tetra_profile(config)
    assert profile["enabled"] is True
    assert profile["surface_nodes_per_reference_length"] == pytest.approx(24.0)
    assert profile["edge_refinement_ratio"] == pytest.approx(1.0)
    defaults = _resolve_mesh_field_defaults(1.0425, config)
    assert defaults["near_body_size"] == pytest.approx(1.0425 / 24.0)
    assert defaults["edge_size"] == pytest.approx(1.0425 / 24.0)
    assert defaults["coarse_first_tetra"]["enabled"] is True


def test_configure_mesh_field_coarse_first_tetra_clamps_size_min_and_raises_floors(tmp_path: Path):
    config = MeshJobConfig(
        component="main_wing",
        geometry=tmp_path / "demo.vsp3",
        out_dir=tmp_path / "out",
        geometry_source="esp_rebuilt",
        geometry_family="thin_sheet_lifting_surface",
        geometry_provider="esp_rebuilt",
        metadata={"coarse_first_tetra_enabled": True},
    )
    gmsh = _FakeGmsh()
    surface_patch_diagnostics = {
        "surface_records": [
            {
                "tag": 5,
                "surface_role": "aircraft",
                "curve_tags": [105, 205],
                "family_hints": ["short_curve_candidate", "high_aspect_strip_candidate"],
            },
            {
                "tag": 31,
                "surface_role": "aircraft",
                "curve_tags": [131, 231],
                "family_hints": [
                    "short_curve_candidate",
                    "high_aspect_strip_candidate",
                    "span_extreme_candidate",
                ],
            },
            {
                "tag": 14,
                "surface_role": "aircraft",
                "curve_tags": [114],
                "family_hints": [],
            },
        ]
    }

    info = _configure_mesh_field(
        gmsh,
        [5, 14, 31],
        [105, 114, 131, 205, 231],
        1.0425,
        config,
        farfield_surface_tags=[33],
        surface_patch_diagnostics=surface_patch_diagnostics,
    )

    expected_near_body = 1.0425 / 24.0
    assert info["coarse_first_tetra"]["enabled"] is True
    assert info["coarse_first_tetra"]["clamp_mesh_size_min_to_near_body"] is True
    assert info["near_body_size"] == pytest.approx(expected_near_body)
    assert info["edge_size"] == pytest.approx(expected_near_body)
    assert info["mesh_size_min"] == pytest.approx(expected_near_body)
    assert gmsh.option.values["Mesh.MeshSizeMin"] == pytest.approx(expected_near_body)
    assert info["surface_policy"]["coarse_first_tetra_active"] is True
    assert info["surface_policy"]["name"] == "esp_rebuilt_native_rule_loft_c1_coarse_first_tetra"
    floors_by_name = {entry["name"]: entry for entry in info["local_size_floors"]}
    assert floors_by_name["span_extreme_strip_floor"]["size"] == pytest.approx(0.12)
    assert floors_by_name["suspect_strip_floor"]["size"] == pytest.approx(0.08)
    algorithms_by_name = {entry["name"]: entry for entry in info["per_surface_algorithms"]}
    assert algorithms_by_name["suspect_strip_family"]["algorithm"] == 5
    assert algorithms_by_name["aircraft_general_surfaces"]["algorithm"] == 5


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


def test_import_scale_to_units_falls_back_to_dominant_span_when_provider_scale_missing(tmp_path: Path):
    from hpa_meshing.schema import Bounds3D

    source = tmp_path / "demo.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    normalized = tmp_path / "normalized.stp"
    normalized.write_text("ISO-10303-21;", encoding="utf-8")
    handle = GeometryHandle(
        source_path=source,
        path=normalized,
        exists=True,
        suffix=".stp",
        loader="provider:esp_rebuilt",
        geometry_source="esp_rebuilt",
        declared_family="thin_sheet_aircraft_assembly",
        component="aircraft_assembly",
        provider="esp_rebuilt",
        provider_status="materialized",
        provider_result=GeometryProviderResult(
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
                bounds=Bounds3D(
                    x_min=-0.0009837188121968,
                    x_max=5.7,
                    y_min=-16.5,
                    y_max=16.5,
                    z_min=-0.7,
                    z_max=1.7,
                ),
                import_bounds=Bounds3D(
                    x_min=-0.9837189121968,
                    x_max=1302.3292691,
                    y_min=-16500.0000001,
                    y_max=16500.0000001,
                    z_min=-68.0367432158,
                    z_max=835.294794189,
                ),
                import_scale_to_units=None,
                backend_rescale_required=False,
            ),
        ),
    )

    scale, units = gmsh_backend_module._import_scale_to_units(handle)

    assert units == "m"
    assert scale == pytest.approx(1.0e-3, rel=1e-6)


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
