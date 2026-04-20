from __future__ import annotations

from pathlib import Path

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
