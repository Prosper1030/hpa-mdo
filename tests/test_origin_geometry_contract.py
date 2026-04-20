from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


def test_build_origin_geometry_contract_reports_empennage(monkeypatch, tmp_path: Path) -> None:
    from hpa_mdo.aero.origin_geometry_contract import build_origin_geometry_contract

    origin_vsp = tmp_path / "origin.vsp3"
    origin_vsp.write_text("stub\n", encoding="utf-8")
    cfg = SimpleNamespace(
        io=SimpleNamespace(vsp_model=origin_vsp, airfoil_dir=tmp_path / "airfoils")
    )

    monkeypatch.setattr(
        "hpa_mdo.aero.origin_geometry_contract.load_config",
        lambda _: cfg,
    )
    monkeypatch.setattr(
        "hpa_mdo.aero.origin_geometry_contract.summarize_vsp_surfaces",
        lambda *args, **kwargs: {
            "source_path": str(origin_vsp),
            "main_wing": {"name": "Main Wing", "controls": []},
            "horizontal_tail": {"name": "Elevator", "controls": []},
            "vertical_fin": {"name": "Fin", "controls": []},
        },
    )

    contract = build_origin_geometry_contract(config_path=tmp_path / "blackcat.yaml")

    assert contract["origin_vsp_path"] == str(origin_vsp.resolve())
    assert contract["tail_geometry_confirmed"] is True
    assert contract["control_surface_contract_confirmed"] is False
    assert contract["surfaces"]["horizontal_tail"]["name"] == "Elevator"
    assert contract["surfaces"]["vertical_fin"]["name"] == "Fin"
