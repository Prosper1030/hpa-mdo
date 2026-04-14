from __future__ import annotations

from pathlib import Path

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
