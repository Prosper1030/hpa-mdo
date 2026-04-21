from __future__ import annotations

import json
import subprocess
from pathlib import Path

from hpa_meshing.gmsh_runtime import load_gmsh
from hpa_meshing.providers.esp_pipeline import (
    _ComponentInputModel,
    _VspWingCandidate,
    _prepare_component_input_model,
    _select_component_candidate,
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


def test_materialize_with_esp_uses_component_subset_in_union_script(monkeypatch, tmp_path: Path):
    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    staging = tmp_path / "provider"
    subset_path = staging / "esp_runtime" / "main_wing.vsp3"
    raw_template = tmp_path / "raw_template.step"
    union_template = tmp_path / "union_template.step"
    _write_boxes_step(raw_template, _raw_symmetry_boxes())
    _write_boxes_step(union_template, _unioned_boxes())

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline._prepare_component_input_model",
        lambda **_: _ComponentInputModel(
            input_model_path=subset_path,
            notes=["component_subset_exported=main_wing"],
            provenance={"requested_component": "main_wing"},
            artifacts={},
        ),
    )
    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline.load_openvsp_reference_data",
        lambda _: {"ref_length": 1.0},
    )

    def fake_runner(args, cwd):
        script_name = Path(args[-1]).name
        if script_name == "rebuild.csm":
            (Path(cwd) / "raw_dump.stp").write_bytes(raw_template.read_bytes())
        elif script_name == "union_groups.csm":
            union_script_text = (staging / "esp_runtime" / "union_groups.csm").read_text(encoding="utf-8")
            assert "main_wing.vsp3" in union_script_text
            (Path(cwd) / "union_groups.step").write_bytes(union_template.read_bytes())
        else:
            raise AssertionError(f"unexpected script {script_name}")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=f"{script_name} ok\n", stderr="")

    result = materialize_with_esp(
        source_path=source,
        staging_dir=staging,
        component="main_wing",
        runner=fake_runner,
        batch_binary="/opt/esp/bin/serveCSM",
    )

    assert result.status == "success"


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


def test_select_component_candidate_distinguishes_main_horizontal_and_vertical_tail():
    candidates = [
        _VspWingCandidate(
            geom_id="main",
            name="Main Wing",
            type_name="Wing",
            normalized_name="mainwing",
            is_symmetric_xz=True,
            x_location=0.0,
            x_rotation_deg=0.0,
            bbox_min=(0.0, 0.0, -0.05),
            bbox_max=(1.3, 16.5, 0.83),
        ),
        _VspWingCandidate(
            geom_id="htail",
            name="Elevator",
            type_name="Wing",
            normalized_name="elevator",
            is_symmetric_xz=True,
            x_location=4.0,
            x_rotation_deg=0.0,
            bbox_min=(4.0, 0.0, -0.04),
            bbox_max=(4.8, 1.5, 0.04),
        ),
        _VspWingCandidate(
            geom_id="vtail",
            name="Fin",
            type_name="Wing",
            normalized_name="fin",
            is_symmetric_xz=False,
            x_location=5.0,
            x_rotation_deg=90.0,
            bbox_min=(5.0, -0.03, -0.7),
            bbox_max=(5.7, 0.03, 1.7),
        ),
    ]

    assert _select_component_candidate("main_wing", candidates).geom_id == "main"
    assert _select_component_candidate("horizontal_tail", candidates).geom_id == "htail"
    assert _select_component_candidate("tail_wing", candidates).geom_id == "htail"
    assert _select_component_candidate("vertical_tail", candidates).geom_id == "vtail"


class _FakePoint:
    def __init__(self, x: float, y: float, z: float):
        self.x = x
        self.y = y
        self.z = z


class _FakeOpenVsp:
    SET_ALL = 0
    SYM_XZ = 2
    NO_END_CAP = 0
    FLAT_END_CAP = 1
    ROUND_END_CAP = 2
    EDGE_END_CAP = 3
    SHARP_END_CAP = 4
    POINT_END_CAP = 5
    ROUND_EXT_END_CAP_NONE = 6
    ROUND_EXT_END_CAP_LE = 7
    ROUND_EXT_END_CAP_TE = 8
    ROUND_EXT_END_CAP_BOTH = 9

    def __init__(self) -> None:
        self._geom_data = {
            "main": {
                "name": "Main Wing",
                "type_name": "Wing",
                "bbox_min": (0.0, 0.0, -0.05),
                "bbox_max": (1.3, 16.5, 0.83),
                "parms": {
                    ("Sym", "Sym_Planar_Flag"): float(self.SYM_XZ),
                    ("XForm", "X_Location"): 0.0,
                    ("XForm", "X_Rotation"): 0.0,
                },
                "xsecs": [
                    {
                        "shape": 12,
                        "params": {
                            "Root_Chord": 1.0,
                            "Tip_Chord": 1.3,
                            "Sweep": 0.0,
                            "Dihedral": 0.0,
                            "Twist": 0.0,
                            "ThickChord": 0.1409,
                            "SectTess_U": 6.0,
                            "TE_Close_Thick": 0.0,
                            "TE_Close_Thick_Chord": 0.0,
                            "LE_Cap_Type": float(self.FLAT_END_CAP),
                            "TE_Cap_Type": float(self.FLAT_END_CAP),
                        },
                    },
                    {
                        "shape": 12,
                        "params": {
                            "Root_Chord": 0.83,
                            "Tip_Chord": 0.435,
                            "Sweep": 1.91,
                            "Dihedral": 5.0,
                            "Twist": 0.0,
                            "ThickChord": 0.1173,
                            "SectTess_U": 15.0,
                            "TE_Close_Thick": 0.0,
                            "TE_Close_Thick_Chord": 0.0,
                            "LE_Cap_Type": float(self.FLAT_END_CAP),
                            "TE_Cap_Type": float(self.ROUND_EXT_END_CAP_TE),
                        },
                    },
                ],
            },
            "htail": {
                "name": "Elevator",
                "type_name": "Wing",
                "bbox_min": (4.0, 0.0, -0.04),
                "bbox_max": (4.8, 1.5, 0.04),
                "parms": {
                    ("Sym", "Sym_Planar_Flag"): float(self.SYM_XZ),
                    ("XForm", "X_Location"): 4.0,
                    ("XForm", "X_Rotation"): 0.0,
                },
                "xsecs": [
                    {
                        "shape": 7,
                        "params": {
                            "Root_Chord": 1.0,
                            "Tip_Chord": 0.8,
                            "Sweep": 0.0,
                            "Dihedral": 0.0,
                            "Twist": 0.0,
                            "ThickChord": 0.09,
                            "SectTess_U": 6.0,
                            "TE_Close_Thick": 0.0,
                            "TE_Close_Thick_Chord": 0.0,
                            "LE_Cap_Type": float(self.FLAT_END_CAP),
                            "TE_Cap_Type": float(self.FLAT_END_CAP),
                        },
                    }
                ],
            },
        }
        self._geom_ids = list(self._geom_data)

    def ClearVSPModel(self) -> None:
        self._geom_ids = list(self._geom_data)

    def ReadVSPFile(self, _path: str) -> None:
        self._geom_ids = list(self._geom_data)

    def Update(self) -> None:
        return None

    def FindGeoms(self):
        return list(self._geom_ids)

    def GetGeomTypeName(self, geom_id: str) -> str:
        return self._geom_data[geom_id]["type_name"]

    def GetGeomName(self, geom_id: str) -> str:
        return self._geom_data[geom_id]["name"]

    def GetGeomBBoxMin(self, geom_id: str) -> _FakePoint:
        return _FakePoint(*self._geom_data[geom_id]["bbox_min"])

    def GetGeomBBoxMax(self, geom_id: str) -> _FakePoint:
        return _FakePoint(*self._geom_data[geom_id]["bbox_max"])

    def FindParm(self, geom_id: str, parm_name: str, group: str):
        if (group, parm_name) in self._geom_data[geom_id]["parms"]:
            return ("geom", geom_id, group, parm_name)
        return ""

    def GetParmVal(self, parm_ref):
        if parm_ref and parm_ref[0] == "geom":
            _, geom_id, group, parm_name = parm_ref
            return self._geom_data[geom_id]["parms"][(group, parm_name)]
        if parm_ref and parm_ref[0] == "xsec":
            _, geom_id, index, parm_name = parm_ref
            return self._geom_data[geom_id]["xsecs"][index]["params"][parm_name]
        raise KeyError(parm_ref)

    def GetGeomChildren(self, _geom_id: str):
        return []

    def GetXSecSurf(self, geom_id: str, _index: int):
        return geom_id

    def GetNumXSec(self, xsec_surf: str) -> int:
        return len(self._geom_data[xsec_surf]["xsecs"])

    def GetXSec(self, xsec_surf: str, index: int):
        return (xsec_surf, index)

    def GetXSecShape(self, xsec_ref) -> int:
        geom_id, index = xsec_ref
        return self._geom_data[geom_id]["xsecs"][index]["shape"]

    def GetXSecParm(self, xsec_ref, parm_name: str):
        geom_id, index = xsec_ref
        if parm_name in self._geom_data[geom_id]["xsecs"][index]["params"]:
            return ("xsec", geom_id, index, parm_name)
        return ""

    def DeleteGeomVec(self, delete_ids):
        self._geom_ids = [geom_id for geom_id in self._geom_ids if geom_id not in set(delete_ids)]

    def WriteVSPFile(self, path: str, _set_index: int) -> None:
        Path(path).write_text("<vsp3/>", encoding="utf-8")


def test_prepare_component_input_model_writes_wing_component_report(monkeypatch, tmp_path: Path):
    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline._load_openvsp",
        lambda: _FakeOpenVsp(),
    )

    result = _prepare_component_input_model(
        source_path=source,
        artifact_dir=artifact_dir,
        component="main_wing",
    )

    wing_report_path = result.artifacts["wing_component_report"]
    wing_report = json.loads(wing_report_path.read_text(encoding="utf-8"))
    assert wing_report["selected_geom_id"] == "main"
    selected = next(item for item in wing_report["candidates"] if item["geom_id"] == "main")
    terminal = selected["section_report"]["terminal_section"]
    assert terminal["params"]["Tip_Chord"] == 0.435
    assert terminal["params"]["LE_Cap_Type_Name"] == "FLAT_END_CAP"
    assert terminal["params"]["TE_Cap_Type_Name"] == "ROUND_EXT_END_CAP_TE"
