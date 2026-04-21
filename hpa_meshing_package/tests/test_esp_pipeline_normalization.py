from __future__ import annotations

import subprocess
from pathlib import Path

from hpa_meshing.gmsh_runtime import load_gmsh
from hpa_meshing.providers.esp_pipeline import (
    _analyze_symmetry_touching_solids,
    _combine_union_groups_with_singletons,
    materialize_with_esp,
)
from hpa_meshing.providers.openvsp_surface_intersection import _probe_step_topology


def _write_boxes_step(path: Path, boxes: list[tuple[float, float, float, float, float, float]]) -> None:
    gmsh = load_gmsh()
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add(path.stem)
    for x, y, z, dx, dy, dz in boxes:
        gmsh.model.occ.addBox(x, y, z, dx, dy, dz)
    gmsh.model.occ.synchronize()
    gmsh.write(str(path))
    gmsh.finalize()


def _raw_symmetry_boxes() -> list[tuple[float, float, float, float, float, float]]:
    return [
        (0.0, -2.0, 0.0, 1.0, 2.0, 0.10),
        (0.0, 0.0, 0.0, 1.0, 2.0, 0.10),
        (3.0, -0.8, 0.0, 0.5, 0.8, 0.05),
        (3.0, 0.0, 0.0, 0.5, 0.8, 0.05),
        (4.5, -0.05, 0.0, 0.3, 0.10, 0.5),
    ]


def _unioned_boxes() -> list[tuple[float, float, float, float, float, float]]:
    return [
        (0.0, -2.0, 0.0, 1.0, 4.0, 0.10),
        (3.0, -0.8, 0.0, 0.5, 1.6, 0.05),
    ]


def test_analyze_symmetry_touching_solids_detects_groups_and_preserves_singleton(tmp_path: Path):
    raw_path = tmp_path / "raw.step"
    _write_boxes_step(raw_path, _raw_symmetry_boxes())

    analysis = _analyze_symmetry_touching_solids(raw_path)

    assert analysis.body_count == 5
    assert len(analysis.touching_groups) == 2
    assert analysis.singleton_body_tags == [5]
    assert analysis.grouped_body_tags == [1, 2, 3, 4]
    assert len(analysis.duplicate_face_pairs) >= 2
    assert len(analysis.internal_cap_face_tags) >= 4


def test_combine_union_groups_with_singletons_produces_clean_external_geometry(tmp_path: Path):
    raw_path = tmp_path / "raw.step"
    union_path = tmp_path / "unioned.step"
    combined_path = tmp_path / "combined.step"
    _write_boxes_step(raw_path, _raw_symmetry_boxes())
    _write_boxes_step(union_path, _unioned_boxes())

    raw_topology = _probe_step_topology(raw_path, tmp_path)
    union_topology = _probe_step_topology(union_path, tmp_path)

    _combine_union_groups_with_singletons(
        raw_step_path=raw_path,
        raw_topology=raw_topology,
        singleton_body_tags=[5],
        union_step_path=union_path,
        union_topology=union_topology,
        output_path=combined_path,
    )

    final_analysis = _analyze_symmetry_touching_solids(combined_path)
    final_topology = _probe_step_topology(combined_path, tmp_path)

    assert final_topology.body_count == 3
    assert final_topology.surface_count == 18
    assert final_analysis.touching_groups == []
    assert final_analysis.duplicate_face_pairs == []
    assert final_analysis.internal_cap_face_tags == []


def test_materialize_with_esp_reports_normalization_before_after_counts(monkeypatch, tmp_path: Path):
    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    staging = tmp_path / "provider"
    raw_template = tmp_path / "raw_template.step"
    union_template = tmp_path / "union_template.step"
    _write_boxes_step(raw_template, _raw_symmetry_boxes())
    _write_boxes_step(union_template, _unioned_boxes())

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline.load_openvsp_reference_data",
        lambda _: {"ref_length": 1.0},
    )

    def fake_runner(args, cwd):
        script_name = Path(args[-1]).name
        if script_name == "rebuild.csm":
            target = Path(cwd) / "raw_dump.stp"
            target.write_bytes(raw_template.read_bytes())
        elif script_name == "union_groups.csm":
            target = Path(cwd) / "union_groups.step"
            target.write_bytes(union_template.read_bytes())
        else:
            raise AssertionError(f"unexpected script {script_name}")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=f"{script_name} ok\n", stderr="")

    result = materialize_with_esp(
        source_path=source,
        staging_dir=staging,
        runner=fake_runner,
        batch_binary="/opt/esp/bin/serveCSM",
    )

    assert result.status == "success"
    assert result.topology is not None
    normalization = result.topology.normalization
    assert normalization["applied"] is True
    assert normalization["raw_counts"]["body_count"] == 5
    assert normalization["normalized_counts"]["body_count"] == 3
    assert normalization["raw_analysis"]["grouped_body_tags"] == [1, 2, 3, 4]
    assert normalization["raw_analysis"]["singleton_body_tags"] == [5]
    assert normalization["raw_analysis"]["internal_cap_face_count"] >= 4
    assert normalization["final_analysis"]["touching_groups"] == []
    assert normalization["final_analysis"]["duplicate_interface_face_pair_count"] == 0


def test_analyze_symmetry_touching_solids_does_not_fuse_non_mirrored_touching_boxes(tmp_path: Path):
    raw_path = tmp_path / "touching_but_not_mirrored.step"
    _write_boxes_step(
        raw_path,
        [
            (0.0, 0.0, 0.0, 1.0, 1.0, 0.10),
            (1.0, 0.2, 0.0, 0.5, 0.6, 0.10),
            (3.0, -0.5, 0.0, 0.4, 1.0, 0.10),
        ],
    )

    analysis = _analyze_symmetry_touching_solids(raw_path)

    assert analysis.touching_groups == []
    assert analysis.grouped_body_tags == []
    assert analysis.singleton_body_tags == [1, 2, 3]
