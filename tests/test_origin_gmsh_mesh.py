from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hpa_mdo.aero.origin_su2 import validate_su2_mesh


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


def _tetrahedron_stl() -> str:
    return """
    solid tetra
      facet normal 0 0 -1
        outer loop
          vertex 0 0 0
          vertex 1 0 0
          vertex 0 1 0
        endloop
      endfacet
      facet normal 0 -1 0
        outer loop
          vertex 0 0 0
          vertex 0 0 1
          vertex 1 0 0
        endloop
      endfacet
      facet normal 1 1 1
        outer loop
          vertex 1 0 0
          vertex 0 0 1
          vertex 0 1 0
        endloop
      endfacet
      facet normal -1 0 0
        outer loop
          vertex 0 0 0
          vertex 0 1 0
          vertex 0 0 1
        endloop
      endfacet
    endsolid tetra
    """


def _write_occ_sheet_step(path: Path) -> Path:
    from hpa_mdo.aero.origin_gmsh_mesh import _gmsh

    path.parent.mkdir(parents=True, exist_ok=True)
    gmsh = _gmsh()
    gmsh.initialize()
    try:
        gmsh.model.add("thin_surface_step")
        gmsh.model.occ.addRectangle(-0.5, -0.25, 0.0, 1.0, 0.5)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    finally:
        gmsh.finalize()
    return path


def test_origin_su2_mesh_presets_have_expected_contract() -> None:
    from hpa_mdo.aero.origin_gmsh_mesh import ORIGIN_SU2_MESH_PRESETS

    assert set(ORIGIN_SU2_MESH_PRESETS) == {
        "baseline",
        "study_coarse",
        "study_medium",
        "study_fine",
    }
    assert ORIGIN_SU2_MESH_PRESETS["study_fine"]["near_body_size_factor"] < ORIGIN_SU2_MESH_PRESETS[
        "study_coarse"
    ]["near_body_size_factor"]
    assert ORIGIN_SU2_MESH_PRESETS["study_fine"]["farfield_size_factor"] < ORIGIN_SU2_MESH_PRESETS[
        "study_coarse"
    ]["farfield_size_factor"]


def test_generate_stl_external_flow_mesh_writes_valid_su2(tmp_path: Path) -> None:
    from hpa_mdo.aero.origin_gmsh_mesh import (
        GmshExternalFlowMeshError,
        generate_stl_external_flow_mesh,
    )

    stl_path = _write_text(tmp_path / "origin_surface.stl", _tetrahedron_stl())
    output_path = tmp_path / "origin_mesh.su2"

    try:
        metadata = generate_stl_external_flow_mesh(
            stl_path,
            output_path,
            options={
                "upstream_factor": 0.8,
                "downstream_factor": 1.2,
                "lateral_factor": 0.9,
                "vertical_factor": 0.9,
                "near_body_size_factor": 0.35,
                "farfield_size_factor": 0.55,
            },
        )
    except GmshExternalFlowMeshError as exc:  # pragma: no cover - env guard
        pytest.skip(str(exc))

    assert output_path.exists()
    assert metadata["MeshMode"] == "stl_external_box"
    assert metadata["PresetName"] == "baseline"
    assert metadata["Nodes"] > 0
    assert metadata["VolumeElements"] > 0
    assert metadata["MarkerElements"]["aircraft"] > 0
    assert metadata["MarkerElements"]["farfield"] > 0

    validation = validate_su2_mesh(output_path)
    assert validation["marker_names"] == ["aircraft", "farfield"]


def test_generate_step_occ_external_flow_mesh_handles_thin_surface_step(tmp_path: Path) -> None:
    from hpa_mdo.aero.origin_gmsh_mesh import (
        GmshExternalFlowMeshError,
        generate_step_occ_external_flow_mesh,
    )

    try:
        step_path = _write_occ_sheet_step(tmp_path / "thin_surface.step")
    except GmshExternalFlowMeshError as exc:  # pragma: no cover - env guard
        pytest.skip(str(exc))

    output_path = tmp_path / "origin_mesh.su2"
    metadata = generate_step_occ_external_flow_mesh(
        step_path,
        output_path,
        options={
            "upstream_factor": 0.8,
            "downstream_factor": 1.2,
            "lateral_factor": 0.9,
            "vertical_factor": 0.9,
            "near_body_size_factor": 0.2,
            "farfield_size_factor": 0.4,
            "distance_min_factor": 0.2,
            "distance_max_factor": 0.5,
        },
    )

    assert output_path.exists()
    assert metadata["MeshMode"] == "step_occ_box"
    assert metadata["BodyVolumeCount"] == 0
    assert metadata["FluidVolumeCount"] > 0
    assert metadata["BodySurfaceCount"] > 0
    assert metadata["FarfieldSurfaceCount"] > 0
    assert metadata["MarkerElements"]["aircraft"] > 0
    assert metadata["MarkerElements"]["farfield"] > 0

    validation = validate_su2_mesh(output_path)
    assert validation["marker_names"] == ["aircraft", "farfield"]


def test_generate_origin_external_flow_mesh_prefers_step_when_available(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from hpa_mdo.aero.origin_gmsh_mesh import generate_origin_external_flow_mesh

    step_path = _write_text(tmp_path / "origin_surface.step", "ISO-10303-21;")
    stl_path = _write_text(tmp_path / "origin_surface.stl", _tetrahedron_stl())
    output_path = tmp_path / "origin_mesh.su2"
    called: dict[str, str] = {}

    def _fake_step(*args, **kwargs) -> dict[str, object]:
        called["mode"] = "step"
        return {
            "MeshMode": "step_occ_box",
            "PresetName": kwargs["preset_name"],
            "MeshFile": str(output_path),
        }

    monkeypatch.setattr(
        "hpa_mdo.aero.origin_gmsh_mesh.generate_step_occ_external_flow_mesh",
        _fake_step,
    )

    metadata = generate_origin_external_flow_mesh(
        step_path=step_path,
        stl_path=stl_path,
        output_path=output_path,
        preset_name="study_medium",
    )

    assert called["mode"] == "step"
    assert metadata["MeshMode"] == "step_occ_box"
    assert metadata["PresetName"] == "study_medium"


def test_generate_origin_external_flow_mesh_falls_back_to_stl(monkeypatch, tmp_path: Path) -> None:
    from hpa_mdo.aero.origin_gmsh_mesh import (
        GmshExternalFlowMeshError,
        generate_origin_external_flow_mesh,
    )

    step_path = _write_text(tmp_path / "origin_surface.step", "ISO-10303-21;")
    stl_path = _write_text(tmp_path / "origin_surface.stl", _tetrahedron_stl())
    output_path = tmp_path / "origin_mesh.su2"

    def _fake_step(*args, **kwargs) -> dict[str, object]:
        raise GmshExternalFlowMeshError("bad step")

    def _fake_stl(*args, **kwargs) -> dict[str, object]:
        return {
            "MeshMode": "stl_external_box",
            "PresetName": kwargs["preset_name"],
            "Nodes": 42,
            "MeshFile": str(output_path),
        }

    monkeypatch.setattr(
        "hpa_mdo.aero.origin_gmsh_mesh.generate_step_occ_external_flow_mesh",
        _fake_step,
    )
    monkeypatch.setattr(
        "hpa_mdo.aero.origin_gmsh_mesh.generate_stl_external_flow_mesh",
        _fake_stl,
    )

    metadata = generate_origin_external_flow_mesh(
        step_path=step_path,
        stl_path=stl_path,
        output_path=output_path,
        preset_name="study_medium",
    )

    assert metadata["MeshMode"] == "stl_external_box_fallback"
    assert metadata["PresetName"] == "study_medium"
    assert metadata["Nodes"] == 42
    assert "FallbackReason" in metadata


def test_generate_origin_external_flow_mesh_falls_back_to_stl_when_step_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from hpa_mdo.aero.origin_gmsh_mesh import generate_origin_external_flow_mesh

    missing_step_path = tmp_path / "origin_surface.step"
    stl_path = _write_text(tmp_path / "origin_surface.stl", _tetrahedron_stl())
    output_path = tmp_path / "origin_mesh.su2"

    def _fake_stl(*args, body_marker, farfield_marker, **kwargs) -> dict[str, object]:
        return {
            "MeshMode": "stl_external_box",
            "PresetName": kwargs["preset_name"],
            "MeshFile": str(output_path),
            "MarkerElements": {body_marker: 1, farfield_marker: 3},
        }

    monkeypatch.setattr(
        "hpa_mdo.aero.origin_gmsh_mesh.generate_stl_external_flow_mesh",
        _fake_stl,
    )

    metadata = generate_origin_external_flow_mesh(
        step_path=missing_step_path,
        stl_path=stl_path,
        output_path=output_path,
        preset_name="study_medium",
        body_marker="wing_surface",
        farfield_marker="outer_box",
    )

    assert metadata["MeshMode"] == "stl_external_box_fallback"
    assert metadata["PresetName"] == "study_medium"
    assert metadata["MarkerElements"] == {"wing_surface": 1, "outer_box": 3}
    assert "FallbackReason" in metadata


def test_remove_duplicate_surface_facets_drops_cross_surface_duplicates() -> None:
    from hpa_mdo.aero.origin_gmsh_mesh import _remove_duplicate_surface_facets

    removed: list[tuple[int, list[int]]] = []
    reclassified: list[bool] = []

    class _FakeMesh:
        def getElements(self, dim: int, tag: int):
            assert dim == 2
            payload = {
                10: ([2], [[1001]], [[1, 2, 3]]),
                11: ([2], [[1002]], [[3, 1, 2]]),
                12: ([2], [[1003]], [[4, 5, 6]]),
            }
            return payload[tag]

        def removeElements(self, dim: int, tag: int, elementTags):
            assert dim == 2
            removed.append((tag, list(elementTags)))

        def reclassifyNodes(self):
            reclassified.append(True)

    gmsh = SimpleNamespace(model=SimpleNamespace(mesh=_FakeMesh()))

    duplicate_count = _remove_duplicate_surface_facets(gmsh, [10, 11, 12])

    assert duplicate_count == 1
    assert removed == [(11, [1002])]
    assert reclassified == [True]


def test_filter_marker_elements_to_volume_nodes_drops_surface_only_facets() -> None:
    from hpa_mdo.aero.origin_gmsh_mesh import _filter_marker_elements_to_volume_nodes

    marker_elements = {
        "aircraft": [
            (5, [0, 1, 2]),
            (5, [2, 3, 99]),
        ],
        "farfield": [
            (5, [0, 1, 3]),
        ],
    }

    filtered = _filter_marker_elements_to_volume_nodes(
        marker_elements,
        volume_node_tags={0, 1, 2, 3},
    )

    assert filtered == {
        "aircraft": [(5, [0, 1, 2])],
        "farfield": [(5, [0, 1, 3])],
    }
