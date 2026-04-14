from __future__ import annotations

from pathlib import Path

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
    assert 'SetParmVal( FindParm( elevator_id, "X_Rel_Location", "XForm" ), 4.000000 );' in text
    assert 'SetParmVal( FindParm( fin_id, "Z_Rel_Location", "XForm" ), -0.700000 );' in text
    assert 'SetParmVal( FindParm( fin_id, "X_Rel_Rotation", "XForm" ), 90.000000 );' in text
    assert 'SetParmVal( GetXSecParm( elevator_tip_xs, "Span" ), 1.500000 );' in text
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

    vsp3_path = VSPBuilder(cfg).build_vsp3(str(tmp_path / "blackcat_004.vsp3"))

    openvsp.ClearVSPModel()
    openvsp.ReadVSPFile(str(vsp3_path))
    openvsp.Update()

    geoms = {
        openvsp.GetGeomName(geom_id): geom_id
        for geom_id in openvsp.FindGeoms()
    }
    wing_id = geoms["MainWing"]
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
    assert sum(areas) == pytest.approx(15.345)
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
    xsec_surf = openvsp.GetXSecSurf(geoms["MainWing"], 0)
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
