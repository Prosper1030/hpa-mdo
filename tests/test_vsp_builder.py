from __future__ import annotations

import math
from pathlib import Path
import subprocess

import pytest

from hpa_mdo.aero import vsp_builder
from hpa_mdo.aero.vsp_builder import VSPBuilder
from hpa_mdo.core.config import load_config


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_vspscript_fallback_includes_empennage_surfaces(tmp_path, monkeypatch) -> None:
    config_path = REPO_ROOT / "configs" / "blackcat_004.yaml"
    cfg = load_config(config_path)

    monkeypatch.setattr(vsp_builder, "_has_openvsp", lambda: False)

    script_path = VSPBuilder(cfg).build_vsp3(str(tmp_path / "blackcat_004.vsp3"))

    text = script_path.read_text(encoding="utf-8")
    assert script_path.suffix == ".vspscript"
    assert 'SetGeomName( wing_id, "MainWing" );' in text
    assert 'SetGeomName( elevator_id, "Elevator" );' in text
    assert 'SetGeomName( fin_id, "Fin" );' in text
    assert 'SetParmVal( FindParm( elevator_id, "X_Rel_Location", "XForm" ), 6.500000 );' in text
    assert 'SetParmVal( FindParm( fin_id, "Z_Rel_Location", "XForm" ), -0.700000 );' in text
    assert 'SetParmVal( FindParm( fin_id, "X_Rel_Rotation", "XForm" ), 90.000000 );' in text
    assert 'SetParmVal( GetXSecParm( elevator_tip_xs, "Span" ), 2.000000 );' in text
    assert 'SetParmVal( GetXSecParm( fin_tip_xs, "Span" ), 2.400000 );' in text
    assert 'SetParmVal( GetXSecParm( fin_xs_1, "ThickChord" ), 0.090000 );' in text
    assert text.count("InsertXSec( wing_id, 1, XS_FOUR_SERIES );") == 5
    assert text.count("SetDriverGroup( wing_id,") == 6
    assert 'SetParmVal( GetXSecParm( seg5_xs, "Span" ), 3.000000 );' in text
    assert 'SetParmVal( GetXSecParm( seg5_xs, "Dihedral" ), 5.454545 );' in text


def test_api_build_preserves_progressive_wing_sections(tmp_path) -> None:
    openvsp = pytest.importorskip("openvsp")
    config_path = REPO_ROOT / "configs" / "blackcat_004.yaml"
    cfg = load_config(config_path, local_paths_path=tmp_path / "missing_local_paths.yaml")
    cfg.io.vsp_model = None

    vsp3_path = VSPBuilder(cfg).build_vsp3(str(tmp_path / "blackcat_004.vsp3"))

    openvsp.ClearVSPModel()
    openvsp.ReadVSPFile(str(vsp3_path))
    openvsp.Update()

    geoms = {
        openvsp.GetGeomName(geom_id): geom_id
        for geom_id in openvsp.FindGeoms()
    }
    wing_id = geoms.get("Main Wing", geoms.get("MainWing"))
    assert wing_id is not None
    xsec_surf = openvsp.GetXSecSurf(wing_id, 0)
    assert openvsp.GetNumXSec(xsec_surf) == 7

    spans = []
    root_chords = []
    tip_chords = []
    dihedrals = []
    areas = []
    for xsec_idx in range(1, 7):
        xs = openvsp.GetXSec(xsec_surf, xsec_idx)
        spans.append(openvsp.GetParmVal(openvsp.GetXSecParm(xs, "Span")))
        root_chords.append(openvsp.GetParmVal(openvsp.GetXSecParm(xs, "Root_Chord")))
        tip_chords.append(openvsp.GetParmVal(openvsp.GetXSecParm(xs, "Tip_Chord")))
        dihedrals.append(openvsp.GetParmVal(openvsp.GetXSecParm(xs, "Dihedral")))
        areas.append(openvsp.GetParmVal(openvsp.GetXSecParm(xs, "Area")))

    assert spans == pytest.approx([1.5, 3.0, 3.0, 3.0, 3.0, 3.0])
    assert root_chords[0] == pytest.approx(cfg.wing.root_chord)
    assert tip_chords[-1] == pytest.approx(cfg.wing.tip_chord)
    # Half-wing area from the config-based linear-taper schedule
    # (root_chord=1.3 → tip_chord=0.435 across half_span=16.5):
    # (1.3 + 0.435) / 2 * 16.5 = 14.31375.  The reference-.vsp3-driven
    # CFD-fidelity path (tested separately) matches the 35.175 m² Sref
    # from the AVL header via the piecewise-linear chord schedule.
    assert sum(areas) == pytest.approx(14.31375, rel=1e-4)
    assert dihedrals == pytest.approx(
        [
            0.2727272727,
            1.0909090909,
            2.1818181818,
            3.2727272727,
            4.3636363636,
            5.4545454545,
        ]
    )


def test_api_build_prefers_reference_vsp_sections_for_cfd_fidelity(tmp_path) -> None:
    openvsp = pytest.importorskip("openvsp")
    reference_path = tmp_path / "reference.vsp3"
    config_path = REPO_ROOT / "configs" / "blackcat_004.yaml"
    cfg = load_config(config_path, local_paths_path=tmp_path / "missing_local_paths.yaml")

    openvsp.ClearVSPModel()
    wing_id = openvsp.AddGeom("WING")
    openvsp.SetGeomName(wing_id, "Main Wing")
    xsec_surf = openvsp.GetXSecSurf(wing_id, 0)
    for _ in range(4):
        openvsp.InsertXSec(wing_id, 1, openvsp.XS_FOUR_SERIES)

    reference_segments = [
        (1.30, 1.30, 4.5, 1.0),
        (1.30, 1.175, 3.0, 2.0),
        (1.175, 1.04, 3.0, 3.0),
        (1.04, 0.83, 3.0, 4.0),
        (0.83, 0.435, 3.0, 5.0),
    ]
    for xsec_idx, (root_chord, tip_chord, span, dihedral) in enumerate(
        reference_segments,
        start=1,
    ):
        openvsp.SetDriverGroup(
            wing_id,
            xsec_idx,
            openvsp.SPAN_WSECT_DRIVER,
            openvsp.ROOTC_WSECT_DRIVER,
            openvsp.TIPC_WSECT_DRIVER,
        )
        xs = openvsp.GetXSec(xsec_surf, xsec_idx)
        openvsp.SetParmVal(openvsp.GetXSecParm(xs, "Root_Chord"), root_chord)
        openvsp.SetParmVal(openvsp.GetXSecParm(xs, "Tip_Chord"), tip_chord)
        openvsp.SetParmVal(openvsp.GetXSecParm(xs, "Span"), span)
        openvsp.SetParmVal(openvsp.GetXSecParm(xs, "Dihedral"), dihedral)
        openvsp.Update()
    openvsp.WriteVSPFile(str(reference_path))

    cfg.io.vsp_model = reference_path
    vsp3_path = VSPBuilder(cfg).build_vsp3(str(tmp_path / "cfd_fidelity.vsp3"))

    openvsp.ClearVSPModel()
    openvsp.ReadVSPFile(str(vsp3_path))
    openvsp.Update()

    geoms = {
        openvsp.GetGeomName(geom_id): geom_id
        for geom_id in openvsp.FindGeoms()
    }
    wing_id = geoms.get("Main Wing", geoms.get("MainWing"))
    assert wing_id is not None
    xsec_surf = openvsp.GetXSecSurf(wing_id, 0)
    assert openvsp.GetNumXSec(xsec_surf) == 7

    spans = []
    root_chords = []
    tip_chords = []
    dihedrals = []
    areas = []
    for xsec_idx in range(1, 7):
        xs = openvsp.GetXSec(xsec_surf, xsec_idx)
        spans.append(openvsp.GetParmVal(openvsp.GetXSecParm(xs, "Span")))
        root_chords.append(openvsp.GetParmVal(openvsp.GetXSecParm(xs, "Root_Chord")))
        tip_chords.append(openvsp.GetParmVal(openvsp.GetXSecParm(xs, "Tip_Chord")))
        dihedrals.append(openvsp.GetParmVal(openvsp.GetXSecParm(xs, "Dihedral")))
        areas.append(openvsp.GetParmVal(openvsp.GetXSecParm(xs, "Area")))

    assert spans == pytest.approx([1.5, 3.0, 3.0, 3.0, 3.0, 3.0])
    assert root_chords == pytest.approx([1.30, 1.30, 1.30, 1.175, 1.04, 0.83])
    assert tip_chords == pytest.approx([1.30, 1.30, 1.175, 1.04, 0.83, 0.435])
    assert dihedrals == pytest.approx([1.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    assert 2.0 * sum(areas) == pytest.approx(35.175)


def test_api_build_from_reference_vsp_preserves_origin_attitude_and_empennage(tmp_path) -> None:
    openvsp = pytest.importorskip("openvsp")
    reference_path = tmp_path / "reference_origin.vsp3"
    config_path = REPO_ROOT / "configs" / "blackcat_004.yaml"
    cfg = load_config(config_path, local_paths_path=tmp_path / "missing_local_paths.yaml")

    openvsp.ClearVSPModel()

    wing_id = openvsp.AddGeom("WING")
    openvsp.SetGeomName(wing_id, "Main Wing")
    openvsp.SetParmVal(openvsp.FindParm(wing_id, "Y_Rel_Rotation", "XForm"), 3.0)
    wing_surf = openvsp.GetXSecSurf(wing_id, 0)
    for _ in range(4):
        openvsp.InsertXSec(wing_id, 1, openvsp.XS_FOUR_SERIES)
    wing_segments = [
        (1.30, 1.30, 4.5, 1.0),
        (1.30, 1.175, 3.0, 2.0),
        (1.175, 1.04, 3.0, 3.0),
        (1.04, 0.83, 3.0, 4.0),
        (0.83, 0.435, 3.0, 5.0),
    ]
    for xsec_idx, (root_chord, tip_chord, span, dihedral) in enumerate(wing_segments, start=1):
        openvsp.SetDriverGroup(
            wing_id,
            xsec_idx,
            openvsp.SPAN_WSECT_DRIVER,
            openvsp.ROOTC_WSECT_DRIVER,
            openvsp.TIPC_WSECT_DRIVER,
        )
        xs = openvsp.GetXSec(wing_surf, xsec_idx)
        openvsp.SetParmVal(openvsp.GetXSecParm(xs, "Root_Chord"), root_chord)
        openvsp.SetParmVal(openvsp.GetXSecParm(xs, "Tip_Chord"), tip_chord)
        openvsp.SetParmVal(openvsp.GetXSecParm(xs, "Span"), span)
        openvsp.SetParmVal(openvsp.GetXSecParm(xs, "Dihedral"), dihedral)

    elevator_id = openvsp.AddGeom("WING")
    openvsp.SetGeomName(elevator_id, "Elevator")
    openvsp.SetParmVal(openvsp.FindParm(elevator_id, "X_Rel_Location", "XForm"), 4.0)
    openvsp.SetParmVal(openvsp.FindParm(elevator_id, "Sym_Planar_Flag", "Sym"), openvsp.SYM_XZ)

    fin_id = openvsp.AddGeom("WING")
    openvsp.SetGeomName(fin_id, "Fin")
    openvsp.SetParmVal(openvsp.FindParm(fin_id, "X_Rel_Location", "XForm"), 5.0)
    openvsp.SetParmVal(openvsp.FindParm(fin_id, "Z_Rel_Location", "XForm"), -0.7)
    openvsp.SetParmVal(openvsp.FindParm(fin_id, "X_Rel_Rotation", "XForm"), 90.0)

    settings_id = openvsp.FindContainer("VSPAEROSettings", 0)
    openvsp.SetParmVal(openvsp.FindParm(settings_id, "Sref", "VSPAERO"), 35.175)
    openvsp.SetParmVal(openvsp.FindParm(settings_id, "bref", "VSPAERO"), 33.0)
    openvsp.SetParmVal(openvsp.FindParm(settings_id, "cref", "VSPAERO"), 1.0425)
    openvsp.Update()
    openvsp.WriteVSPFile(str(reference_path))

    cfg.io.vsp_model = reference_path
    built_path = VSPBuilder(cfg).build_vsp3(str(tmp_path / "from_reference.vsp3"))

    openvsp.ClearVSPModel()
    openvsp.ReadVSPFile(str(built_path))
    openvsp.Update()

    geoms = {
        openvsp.GetGeomName(geom_id): geom_id
        for geom_id in openvsp.FindGeoms()
    }
    wing_id = geoms.get("Main Wing", geoms.get("MainWing"))
    assert wing_id is not None
    assert openvsp.GetParmVal(openvsp.FindParm(wing_id, "Y_Rel_Rotation", "XForm")) == pytest.approx(3.0)
    assert openvsp.GetParmVal(openvsp.FindParm(geoms["Elevator"], "X_Rel_Location", "XForm")) == pytest.approx(4.0)
    assert openvsp.GetParmVal(openvsp.FindParm(geoms["Fin"], "X_Rel_Location", "XForm")) == pytest.approx(5.0)
    assert openvsp.GetParmVal(openvsp.FindParm(geoms["Fin"], "Z_Rel_Location", "XForm")) == pytest.approx(-0.7)
    settings_id = openvsp.FindContainer("VSPAEROSettings", 0)
    assert openvsp.GetParmVal(openvsp.FindParm(settings_id, "RefFlag", "VSPAERO")) == pytest.approx(0.0)
    assert openvsp.GetParmVal(openvsp.FindParm(settings_id, "MACFlag", "VSPAERO")) == pytest.approx(0.0)
    assert openvsp.GetParmVal(openvsp.FindParm(settings_id, "Sref", "VSPAERO")) == pytest.approx(35.175)
    assert openvsp.GetParmVal(openvsp.FindParm(settings_id, "bref", "VSPAERO")) == pytest.approx(33.0)
    assert openvsp.GetParmVal(openvsp.FindParm(settings_id, "cref", "VSPAERO")) == pytest.approx(1.0425)


def test_dihedral_multiplier_refits_segment_angles_from_scaled_station_z(tmp_path) -> None:
    config_path = REPO_ROOT / "configs" / "blackcat_004.yaml"
    cfg = load_config(config_path, local_paths_path=tmp_path / "missing_local_paths.yaml")
    builder = VSPBuilder(cfg, dihedral_multiplier=3.6, dihedral_exponent=1.0)

    schedule = [
        {
            "y": 0.0,
            "chord": 1.30,
            "dihedral_deg": 1.0,
            "segment_dihedral_deg": 1.0,
            "airfoil": "fx76mp140",
            "source": "reference_vsp",
        },
        {
            "y": 1.5,
            "chord": 1.30,
            "dihedral_deg": 1.0,
            "segment_dihedral_deg": 1.0,
            "airfoil": "fx76mp140",
            "source": "reference_vsp",
        },
        {
            "y": 4.5,
            "chord": 1.175,
            "dihedral_deg": 2.0,
            "segment_dihedral_deg": 2.0,
            "airfoil": "fx76mp140",
            "source": "reference_vsp",
        },
        {
            "y": 7.5,
            "chord": 1.04,
            "dihedral_deg": 3.0,
            "segment_dihedral_deg": 3.0,
            "airfoil": "fx76mp140",
            "source": "reference_vsp",
        },
        {
            "y": 10.5,
            "chord": 0.83,
            "dihedral_deg": 4.0,
            "segment_dihedral_deg": 4.0,
            "airfoil": "fx76mp140",
            "source": "reference_vsp",
        },
        {
            "y": 13.5,
            "chord": 0.62,
            "dihedral_deg": 5.0,
            "segment_dihedral_deg": 5.0,
            "airfoil": "fx76mp140",
            "source": "reference_vsp",
        },
        {
            "y": 16.5,
            "chord": 0.435,
            "dihedral_deg": 5.0,
            "segment_dihedral_deg": 5.0,
            "airfoil": "clarkysm",
            "source": "reference_vsp",
        },
    ]

    scaled = builder._apply_dihedral_multiplier_to_schedule(schedule)

    base_z = [0.0]
    refit_z = [0.0]
    for idx in range(1, len(schedule)):
        dy = schedule[idx]["y"] - schedule[idx - 1]["y"]
        base_z.append(
            base_z[-1]
            + dy * math.tan(math.radians(schedule[idx]["segment_dihedral_deg"]))
        )
        refit_z.append(
            refit_z[-1]
            + dy * math.tan(math.radians(scaled[idx]["segment_dihedral_deg"]))
        )

    expected_z = []
    for item, z_val in zip(schedule, base_z):
        eta = item["y"] / cfg.half_span
        expected_z.append(z_val * (1.0 + 2.6 * eta))

    assert [item["y"] for item in scaled] == [item["y"] for item in schedule]
    assert [item["chord"] for item in scaled] == [item["chord"] for item in schedule]
    assert refit_z == pytest.approx(expected_z)
    assert scaled[1]["segment_dihedral_deg"] > schedule[1]["segment_dihedral_deg"]
    assert scaled[-1]["segment_dihedral_deg"] > schedule[-1]["segment_dihedral_deg"]


def test_extract_reference_schedule_uses_introspected_airfoils(tmp_path, monkeypatch) -> None:
    config_path = REPO_ROOT / "configs" / "blackcat_004.yaml"
    cfg = load_config(config_path, local_paths_path=tmp_path / "missing_local_paths.yaml")
    builder = VSPBuilder(cfg)

    monkeypatch.setattr(
        vsp_builder,
        "_extract_airfoil_refs",
        lambda _vsp, _wing_id, _schedule, airfoil_dir=None: [
            {"station_y": 0.0, "name": "fx76mp140"},
            {"station_y": 4.5, "name": "fx76mp140"},
            {"station_y": 16.5, "name": "clarkysm"},
        ],
    )

    class _FakeVSP:
        def GetXSecSurf(self, wing_id, surf_idx):
            assert wing_id == "wing"
            assert surf_idx == 0
            return "surf"

        def GetNumXSec(self, surf):
            assert surf == "surf"
            return 3

        def GetXSec(self, surf, idx):
            assert surf == "surf"
            return idx

        def GetXSecParm(self, xs, name):
            values = {
                1: {"Root_Chord": 1.3, "Tip_Chord": 1.175, "Span": 4.5, "Dihedral": 1.0},
                2: {"Root_Chord": 1.175, "Tip_Chord": 0.435, "Span": 12.0, "Dihedral": 5.0},
            }
            return values[xs][name]

        def GetParmVal(self, value):
            return value

    schedule = builder._extract_reference_wing_schedule(_FakeVSP(), "wing")

    assert [item["y"] for item in schedule] == pytest.approx([0.0, 4.5, 16.5])
    assert [item["airfoil"] for item in schedule] == ["fx76mp140", "fx76mp140", "clarkysm"]


def test_vsp_builder_rejects_unknown_vspaero_analysis_method(tmp_path) -> None:
    config_path = REPO_ROOT / "configs" / "blackcat_004.yaml"
    cfg = load_config(config_path, local_paths_path=tmp_path / "missing_local_paths.yaml")

    with pytest.raises(ValueError, match="vspaero_analysis_method"):
        VSPBuilder(cfg, vspaero_analysis_method="bad_method")


def test_vsp_builder_panel_mode_uses_thick_geometry_sets(tmp_path) -> None:
    config_path = REPO_ROOT / "configs" / "blackcat_004.yaml"
    cfg = load_config(config_path, local_paths_path=tmp_path / "missing_local_paths.yaml")
    builder = VSPBuilder(cfg, vspaero_analysis_method="panel")
    fake_vsp = type("FakeVSP", (), {"SET_ALL": 0, "SET_NONE": -1})()

    geom_set, thin_geom_set = builder._vspaero_geom_set_values(fake_vsp)

    assert (geom_set, thin_geom_set) == (0, -1)


def test_run_vspaero_cli_preserves_selected_analysis_method_metadata(tmp_path, monkeypatch) -> None:
    config_path = REPO_ROOT / "configs" / "blackcat_004.yaml"
    cfg = load_config(config_path, local_paths_path=tmp_path / "missing_local_paths.yaml")
    builder = VSPBuilder(cfg, vspaero_analysis_method="panel")
    vsp3_path = tmp_path / "blackcat_004.vsp3"
    vsp3_path.write_text("dummy\n", encoding="utf-8")

    monkeypatch.setattr(vsp_builder, "_resolve_vspaero_binary", lambda: "/tmp/vspaero")
    monkeypatch.setattr(
        builder,
        "_load_vspaero_reference_values_from_file",
        lambda _vsp3: {
            "sref": 35.175,
            "bref": 33.0,
            "cref": 1.0425,
            "xcg": 0.0,
            "ycg": 0.0,
            "zcg": 0.0,
        },
    )

    def _fake_run(cmd, capture_output, text, timeout, cwd):
        assert cmd[0] == "/tmp/vspaero"
        out_dir = Path(cwd)
        (out_dir / "blackcat_004.lod").write_text("lod\n", encoding="utf-8")
        (out_dir / "blackcat_004.polar").write_text("polar\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(vsp_builder.subprocess, "run", _fake_run)

    result = builder._run_vspaero_cli(vsp3_path, [-2.0, 0.0, 2.0], tmp_path)

    assert result["success"] is True
    assert result["analysis_method"] == "panel"
    assert result["solver_backend"] == "vspaero_cli"
    setup_text = (tmp_path / "blackcat_004.vspaero").read_text(encoding="utf-8")
    assert "Sref = 35.175000" in setup_text
    assert "bref = 33.000000" in setup_text
    assert "cref = 1.042500" in setup_text
    assert "ReCref = 464126.712329" in setup_text


def test_current_vspaero_reference_values_prefer_model_settings(tmp_path) -> None:
    openvsp = pytest.importorskip("openvsp")
    config_path = REPO_ROOT / "configs" / "blackcat_004.yaml"
    cfg = load_config(config_path, local_paths_path=tmp_path / "missing_local_paths.yaml")
    builder = VSPBuilder(cfg)

    openvsp.ClearVSPModel()
    wing_id = openvsp.AddGeom("WING")
    openvsp.SetGeomName(wing_id, "Main Wing")
    xsec_surf = openvsp.GetXSecSurf(wing_id, 0)
    for _ in range(4):
        openvsp.InsertXSec(wing_id, 1, openvsp.XS_FOUR_SERIES)
    segments = [
        (1.30, 1.30, 4.5, 1.0),
        (1.30, 1.175, 3.0, 2.0),
        (1.175, 1.04, 3.0, 3.0),
        (1.04, 0.83, 3.0, 4.0),
        (0.83, 0.435, 3.0, 5.0),
    ]
    for xsec_idx, (root_chord, tip_chord, span, dihedral) in enumerate(segments, start=1):
        openvsp.SetDriverGroup(
            wing_id,
            xsec_idx,
            openvsp.SPAN_WSECT_DRIVER,
            openvsp.ROOTC_WSECT_DRIVER,
            openvsp.TIPC_WSECT_DRIVER,
        )
        xs = openvsp.GetXSec(xsec_surf, xsec_idx)
        openvsp.SetParmVal(openvsp.GetXSecParm(xs, "Root_Chord"), root_chord)
        openvsp.SetParmVal(openvsp.GetXSecParm(xs, "Tip_Chord"), tip_chord)
        openvsp.SetParmVal(openvsp.GetXSecParm(xs, "Span"), span)
        openvsp.SetParmVal(openvsp.GetXSecParm(xs, "Dihedral"), dihedral)
    settings_id = openvsp.FindContainer("VSPAEROSettings", 0)
    openvsp.SetParmVal(openvsp.FindParm(settings_id, "Sref", "VSPAERO"), 35.175)
    openvsp.SetParmVal(openvsp.FindParm(settings_id, "bref", "VSPAERO"), 33.0)
    openvsp.SetParmVal(openvsp.FindParm(settings_id, "cref", "VSPAERO"), 1.0425)
    openvsp.Update()

    refs = builder._current_vspaero_reference_values(openvsp)

    assert refs["sref"] == pytest.approx(35.175)
    assert refs["bref"] == pytest.approx(33.0)
    assert refs["cref"] == pytest.approx(1.0425)


def test_write_vspaero_reference_values_forces_manual_origin_refs(tmp_path) -> None:
    openvsp = pytest.importorskip("openvsp")
    config_path = REPO_ROOT / "configs" / "blackcat_004.yaml"
    cfg = load_config(config_path, local_paths_path=tmp_path / "missing_local_paths.yaml")

    openvsp.ClearVSPModel()
    wing_id = openvsp.AddGeom("WING")
    openvsp.SetGeomName(wing_id, "Main Wing")
    xsec_surf = openvsp.GetXSecSurf(wing_id, 0)
    for _ in range(4):
        openvsp.InsertXSec(wing_id, 1, openvsp.XS_FOUR_SERIES)
    for xsec_idx, (root_chord, tip_chord, span) in enumerate(
        [
            (1.30, 1.30, 4.5),
            (1.30, 1.175, 3.0),
            (1.175, 1.04, 3.0),
            (1.04, 0.83, 3.0),
            (0.83, 0.435, 3.0),
        ],
        start=1,
    ):
        openvsp.SetDriverGroup(
            wing_id,
            xsec_idx,
            openvsp.SPAN_WSECT_DRIVER,
            openvsp.ROOTC_WSECT_DRIVER,
            openvsp.TIPC_WSECT_DRIVER,
        )
        xs = openvsp.GetXSec(xsec_surf, xsec_idx)
        openvsp.SetParmVal(openvsp.GetXSecParm(xs, "Root_Chord"), root_chord)
        openvsp.SetParmVal(openvsp.GetXSecParm(xs, "Tip_Chord"), tip_chord)
        openvsp.SetParmVal(openvsp.GetXSecParm(xs, "Span"), span)
    openvsp.Update()

    VSPBuilder(cfg)._write_vspaero_reference_values(
        openvsp,
        {"sref": 35.175, "bref": 33.0, "cref": 1.0425, "xcg": 0.0, "ycg": 0.0, "zcg": 0.0},
    )

    settings_id = openvsp.FindContainer("VSPAEROSettings", 0)
    assert openvsp.GetParmVal(openvsp.FindParm(settings_id, "RefFlag", "VSPAERO")) == pytest.approx(0.0)
    assert openvsp.GetParmVal(openvsp.FindParm(settings_id, "MACFlag", "VSPAERO")) == pytest.approx(0.0)
    assert openvsp.GetParmVal(openvsp.FindParm(settings_id, "cref", "VSPAERO")) == pytest.approx(1.0425)


def test_preferred_vspaero_reference_values_prefers_origin_vsp(tmp_path, monkeypatch) -> None:
    config_path = REPO_ROOT / "configs" / "blackcat_004.yaml"
    cfg = load_config(config_path, local_paths_path=tmp_path / "missing_local_paths.yaml")
    origin_vsp = tmp_path / "origin.vsp3"
    origin_vsp.write_text("origin\n", encoding="utf-8")
    cfg.io.vsp_model = origin_vsp
    builder = VSPBuilder(cfg)
    seen: list[Path] = []

    def _fake_load(path: Path) -> dict[str, float]:
        seen.append(Path(path))
        return {"sref": 35.175, "bref": 33.0, "cref": 1.0425, "xcg": 0.0, "ycg": 0.0, "zcg": 0.0}

    monkeypatch.setattr(builder, "_load_vspaero_reference_values_from_file", _fake_load)

    refs = builder._preferred_vspaero_reference_values(tmp_path / "candidate.vsp3")

    assert refs["cref"] == pytest.approx(1.0425)
    assert seen == [origin_vsp.resolve()]
