from __future__ import annotations

import json
import subprocess
from pathlib import Path

from hpa_meshing.gmsh_runtime import load_gmsh
from hpa_meshing.providers.esp_pipeline import (
    _ComponentInputModel,
    _NativeRebuildModel,
    _NativeSectionRecord,
    _NativeSurfaceRecord,
    _VspWingCandidate,
    _apply_terminal_strip_suppression,
    _build_topology_lineage_report,
    _build_native_rebuild_model,
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


def _sample_airfoil_coords(scale: float = 1.0) -> tuple[tuple[float, float], ...]:
    return (
        (1.0, 0.0),
        (0.75, 0.035 * scale),
        (0.35, 0.055 * scale),
        (0.0, 0.0),
        (0.35, -0.040 * scale),
        (0.75, -0.018 * scale),
        (1.0, 0.0),
    )


def _sample_native_rebuild_model(source: Path) -> _NativeRebuildModel:
    return _NativeRebuildModel(
        source_path=source,
        surfaces=(
            _NativeSurfaceRecord(
                component="main_wing",
                geom_id="main",
                name="Main Wing",
                caps_group="main_wing",
                symmetric_xz=True,
                sections=(
                    _NativeSectionRecord(
                        x_le=0.0,
                        y_le=0.0,
                        z_le=0.0,
                        chord=1.30,
                        twist_deg=0.0,
                        airfoil_name="NACA 2412",
                        airfoil_source="inline_coordinates",
                        airfoil_coordinates=_sample_airfoil_coords(),
                        thickness_tc=0.12,
                        camber=0.02,
                        camber_loc=0.4,
                    ),
                    _NativeSectionRecord(
                        x_le=0.10,
                        y_le=16.5,
                        z_le=1.70,
                        chord=0.435,
                        twist_deg=0.0,
                        airfoil_name="NACA 2412",
                        airfoil_source="inline_coordinates",
                        airfoil_coordinates=_sample_airfoil_coords(0.8),
                        thickness_tc=0.12,
                        camber=0.02,
                        camber_loc=0.4,
                    ),
                ),
            ),
        ),
        notes=("unit-test-native-model",),
    )


def _sample_tip_strip_airfoil_coords() -> tuple[tuple[float, float], ...]:
    return (
        (1.0, 0.0),
        (0.995, 0.0015),
        (0.72, 0.032),
        (0.34, 0.048),
        (0.0, 0.0),
        (0.34, -0.034),
        (0.72, -0.020),
        (0.995, -0.0015),
        (1.0, 0.0),
    )


def _sample_tip_strip_candidate_model(source: Path) -> _NativeRebuildModel:
    return _NativeRebuildModel(
        source_path=source,
        surfaces=(
            _NativeSurfaceRecord(
                component="main_wing",
                geom_id="main",
                name="Main Wing",
                caps_group="main_wing",
                symmetric_xz=True,
                sections=(
                    _NativeSectionRecord(
                        x_le=0.0,
                        y_le=0.0,
                        z_le=0.0,
                        chord=1.30,
                        twist_deg=0.0,
                        airfoil_name="NACA 2412",
                        airfoil_source="inline_coordinates",
                        airfoil_coordinates=_sample_airfoil_coords(),
                        thickness_tc=0.12,
                        camber=0.02,
                        camber_loc=0.4,
                    ),
                    _NativeSectionRecord(
                        x_le=0.10,
                        y_le=16.5,
                        z_le=1.70,
                        chord=0.435,
                        twist_deg=0.0,
                        airfoil_name="NACA 2412",
                        airfoil_source="inline_coordinates",
                        airfoil_coordinates=_sample_tip_strip_airfoil_coords(),
                        thickness_tc=0.12,
                        camber=0.02,
                        camber_loc=0.4,
                    ),
                ),
            ),
        ),
        notes=("unit-test-tip-strip-model",),
    )


def test_build_topology_lineage_report_identifies_terminal_tip_strip_candidates(tmp_path: Path):
    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")

    report = _build_topology_lineage_report(_sample_tip_strip_candidate_model(source))

    assert report["status"] == "captured"
    assert report["surface_count"] == 1
    surface = report["surfaces"][0]
    candidates = surface["terminal_strip_candidates"]
    assert [candidate["side"] for candidate in candidates] == ["left_tip", "right_tip"]
    assert all(candidate["would_suppress"] is True for candidate in candidates)
    assert all(candidate["source_section_index"] == 1 for candidate in candidates)
    assert all(candidate["seam_adjacent_edge_lengths_m"][0] < 0.003 for candidate in candidates)
    assert all(candidate["seam_adjacent_edge_lengths_m"][1] < 0.003 for candidate in candidates)


def test_apply_terminal_strip_suppression_rewrites_tip_candidate_section(tmp_path: Path):
    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    model = _sample_tip_strip_candidate_model(source)

    suppressed_model, report = _apply_terminal_strip_suppression(model)

    assert report["applied"] is True
    surface_report = report["surfaces"][0]
    assert surface_report["suppressed_source_section_indices"] == [1]
    original_coords = model.surfaces[0].sections[1].airfoil_coordinates
    suppressed_coords = suppressed_model.surfaces[0].sections[1].airfoil_coordinates
    assert len(suppressed_coords) < len(original_coords)
    assert suppressed_coords[0] != original_coords[0]
    assert suppressed_coords[-1] == suppressed_coords[0]
    assert surface_report["suppressed_sections"][0]["trim_count_per_side"] >= 1
    assert (
        surface_report["suppressed_sections"][0]["bridge_length_m"]
        >= surface_report["suppressed_sections"][0]["suppression_threshold_m"]
    )


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
    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline._build_native_rebuild_model",
        lambda **_: _sample_native_rebuild_model(source),
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
    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline._build_native_rebuild_model",
        lambda **_: _sample_native_rebuild_model(subset_path),
    )

    def fake_runner(args, cwd):
        script_name = Path(args[-1]).name
        if script_name == "rebuild.csm":
            (Path(cwd) / "raw_dump.stp").write_bytes(raw_template.read_bytes())
        elif script_name == "union_groups.csm":
            union_script_text = (staging / "esp_runtime" / "union_groups.csm").read_text(encoding="utf-8")
            assert "UDPRIM vsp3" not in union_script_text
            assert "rule" in union_script_text.lower()
            assert "main_wing" in union_script_text
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


class _FakeAirfoilPoint:
    def __init__(self, x: float, y: float, z: float):
        self.x = x
        self.y = y
        self.z = z


class _FakeNativeOpenVsp(_FakeOpenVsp):
    XS_FOUR_SERIES = 7
    XS_FILE_AIRFOIL = 1

    def __init__(self) -> None:
        super().__init__()
        self._geom_data["main"]["parms"].update(
            {
                ("XForm", "Y_Location"): 0.0,
                ("XForm", "Z_Location"): 0.0,
                ("XForm", "Y_Rotation"): 0.0,
                ("XForm", "Z_Rotation"): 0.0,
            }
        )
        self._geom_data["main"]["xsecs"] = [
            {
                "shape": self.XS_FOUR_SERIES,
                "params": {
                    "Root_Chord": 1.30,
                    "Tip_Chord": 1.30,
                    "Sweep": 0.0,
                    "Sweep_Location": 0.25,
                    "Span": 0.0,
                    "Dihedral": 0.0,
                    "Twist": 0.0,
                    "ThickChord": 0.1409,
                    "Camber": 0.02,
                    "CamberLoc": 0.4,
                },
            },
            {
                "shape": self.XS_FOUR_SERIES,
                "params": {
                    "Root_Chord": 1.30,
                    "Tip_Chord": 0.435,
                    "Sweep": 1.91,
                    "Sweep_Location": 0.25,
                    "Span": 16.5,
                    "Dihedral": 5.0,
                    "Twist": 0.0,
                    "ThickChord": 0.1173,
                    "Camber": 0.02,
                    "CamberLoc": 0.4,
                },
            },
        ]
        self._geom_data["htail"]["parms"].update(
            {
                ("XForm", "Y_Location"): 0.0,
                ("XForm", "Z_Location"): 0.0,
                ("XForm", "Y_Rotation"): 0.0,
                ("XForm", "Z_Rotation"): 0.0,
            }
        )
        self._geom_data["htail"]["xsecs"] = [
            {
                "shape": self.XS_FOUR_SERIES,
                "params": {
                    "Root_Chord": 0.8,
                    "Tip_Chord": 0.8,
                    "Sweep": 0.0,
                    "Sweep_Location": 0.25,
                    "Span": 0.0,
                    "Dihedral": 0.0,
                    "Twist": 0.0,
                    "ThickChord": 0.09,
                    "Camber": 0.0,
                    "CamberLoc": 0.4,
                },
            },
            {
                "shape": self.XS_FOUR_SERIES,
                "params": {
                    "Root_Chord": 0.8,
                    "Tip_Chord": 0.7,
                    "Sweep": 4.0,
                    "Sweep_Location": 0.25,
                    "Span": 1.5,
                    "Dihedral": 0.0,
                    "Twist": 0.0,
                    "ThickChord": 0.09,
                    "Camber": 0.0,
                    "CamberLoc": 0.4,
                },
            },
        ]
        self._geom_data["fin"] = {
            "name": "Fin",
            "type_name": "Wing",
            "bbox_min": (5.0, -0.03, -0.7),
            "bbox_max": (5.7, 0.03, 1.7),
            "parms": {
                ("Sym", "Sym_Planar_Flag"): 0.0,
                ("XForm", "X_Location"): 5.0,
                ("XForm", "Y_Location"): 0.0,
                ("XForm", "Z_Location"): -0.7,
                ("XForm", "X_Rotation"): 90.0,
                ("XForm", "Y_Rotation"): 0.0,
                ("XForm", "Z_Rotation"): 0.0,
            },
            "xsecs": [
                {
                    "shape": self.XS_FOUR_SERIES,
                    "params": {
                        "Root_Chord": 0.7,
                        "Tip_Chord": 0.7,
                        "Sweep": 0.0,
                        "Sweep_Location": 0.25,
                        "Span": 0.0,
                        "Dihedral": 0.0,
                        "Twist": 0.0,
                        "ThickChord": 0.09,
                        "Camber": 0.0,
                        "CamberLoc": 0.4,
                    },
                },
                {
                    "shape": self.XS_FOUR_SERIES,
                    "params": {
                        "Root_Chord": 0.7,
                        "Tip_Chord": 0.5,
                        "Sweep": 5.0,
                        "Sweep_Location": 0.25,
                        "Span": 2.4,
                        "Dihedral": 0.0,
                        "Twist": 0.0,
                        "ThickChord": 0.09,
                        "Camber": 0.0,
                        "CamberLoc": 0.4,
                    },
                },
            ],
        }
        self._geom_ids = list(self._geom_data)

    def GetAirfoilUpperPnts(self, xsec_ref):
        geom_id, index = xsec_ref
        chord = self._geom_data[geom_id]["xsecs"][index]["params"].get("Tip_Chord", 1.0)
        return [
            _FakeAirfoilPoint(1.0 * chord, 0.0, 0.0),
            _FakeAirfoilPoint(0.6 * chord, 0.0, 0.05 * chord),
            _FakeAirfoilPoint(0.0, 0.0, 0.0),
        ]

    def GetAirfoilLowerPnts(self, xsec_ref):
        geom_id, index = xsec_ref
        chord = self._geom_data[geom_id]["xsecs"][index]["params"].get("Tip_Chord", 1.0)
        return [
            _FakeAirfoilPoint(0.0, 0.0, 0.0),
            _FakeAirfoilPoint(0.6 * chord, 0.0, -0.04 * chord),
            _FakeAirfoilPoint(1.0 * chord, 0.0, 0.0),
        ]


def test_build_native_rebuild_model_extracts_canonical_surfaces(monkeypatch, tmp_path: Path):
    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline._load_openvsp",
        lambda: _FakeNativeOpenVsp(),
    )

    model = _build_native_rebuild_model(
        source_path=source,
        component="aircraft_assembly",
    )

    components = [surface.component for surface in model.surfaces]
    assert components == ["main_wing", "horizontal_tail", "vertical_tail"]

    main_wing = model.surfaces[0]
    assert main_wing.symmetric_xz is True
    assert len(main_wing.sections) == 2
    assert main_wing.sections[1].y_le == 16.5
    assert len(main_wing.sections[0].airfoil_coordinates) >= 5

    vertical_tail = model.surfaces[2]
    assert vertical_tail.symmetric_xz is False
    assert vertical_tail.sections[-1].z_le > vertical_tail.sections[0].z_le


def test_materialize_with_esp_writes_native_rule_loft_script(monkeypatch, tmp_path: Path):
    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    staging = tmp_path / "provider"

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline._build_native_rebuild_model",
        lambda **_: _sample_native_rebuild_model(source),
    )

    def fake_runner(args, cwd):
        exported = Path(cwd) / "raw_dump.stp"
        exported.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="serveCSM ok\n", stderr="")

    result = materialize_with_esp(
        source_path=source,
        staging_dir=staging,
        runner=fake_runner,
        batch_binary="/opt/esp/bin/serveCSM",
    )

    assert result.status == "success"
    script_text = result.script_path.read_text(encoding="utf-8")
    assert "UDPRIM vsp3" not in script_text
    assert "rule" in script_text.lower()
    assert "ATTRIBUTE _name $main_wing" in script_text
    assert "ATTRIBUTE capsGroup $main_wing" in script_text


def test_materialize_with_esp_writes_topology_lineage_report(monkeypatch, tmp_path: Path):
    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    staging = tmp_path / "provider"

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline._build_native_rebuild_model",
        lambda **_: _sample_tip_strip_candidate_model(source),
    )

    def fake_runner(args, cwd):
        exported = Path(cwd) / "raw_dump.stp"
        exported.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="serveCSM ok\n", stderr="")

    result = materialize_with_esp(
        source_path=source,
        staging_dir=staging,
        runner=fake_runner,
        batch_binary="/opt/esp/bin/serveCSM",
    )

    assert result.status == "success"
    lineage_path = result.artifacts["topology_lineage_report"]
    payload = json.loads(lineage_path.read_text(encoding="utf-8"))
    assert payload["status"] == "captured"
    candidates = payload["surfaces"][0]["terminal_strip_candidates"]
    assert [candidate["side"] for candidate in candidates] == ["left_tip", "right_tip"]
    assert all(candidate["would_suppress"] is True for candidate in candidates)


def test_materialize_with_esp_writes_topology_suppression_report(monkeypatch, tmp_path: Path):
    source = tmp_path / "model.vsp3"
    source.write_text("<vsp3/>", encoding="utf-8")
    staging = tmp_path / "provider"

    monkeypatch.setattr(
        "hpa_meshing.providers.esp_pipeline._build_native_rebuild_model",
        lambda **_: _sample_tip_strip_candidate_model(source),
    )

    def fake_runner(args, cwd):
        exported = Path(cwd) / "raw_dump.stp"
        exported.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n", encoding="utf-8")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="serveCSM ok\n", stderr="")

    result = materialize_with_esp(
        source_path=source,
        staging_dir=staging,
        runner=fake_runner,
        batch_binary="/opt/esp/bin/serveCSM",
    )

    assert result.status == "success"
    suppression_path = result.artifacts["topology_suppression_report"]
    payload = json.loads(suppression_path.read_text(encoding="utf-8"))
    assert payload["applied"] is True
    assert payload["surfaces"][0]["suppressed_source_section_indices"] == [1]
