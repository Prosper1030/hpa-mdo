from __future__ import annotations

from types import SimpleNamespace

import hpa_mdo.aero.vsp_aero as vsp_aero_module
from hpa_mdo.aero.vsp_aero import VSPAeroParser


def _write_sample_lod(tmp_path):
    path = tmp_path / "sample.lod"
    path.write_text(
        "\n".join(
            [
                "Sref_ 35.1750000 Lunit^2",
                "Bref_ 33.0000000 Lunit",
                "Cref_ 1.1000000 Lunit",
                "AoA_ 3.5000000 Deg",
                "Rho_ 1.2250000 kg/m^3",
                "Vinf_ 6.5000000 m/s",
                "Wing S Xavg Yavg Zavg Chord V/Vref Cl Cd Cs Cx Cy Cz Cmx Cmy Cmz",
                "1 0 0 0.0 0 1.2 1 0.6 0.02 0 0 0 0 0 -0.08 0",
                "1 0 0 1.0 0 1.1 1 0.62 0.021 0 0 0 0 0 -0.079 0",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_cache_returns_same_object_on_second_call(tmp_path):
    VSPAeroParser._parse_cache.clear()
    lod_path = _write_sample_lod(tmp_path)
    parser = VSPAeroParser(lod_path)

    first = parser.parse()
    second = parser.parse()

    assert len(first) > 0
    assert second is first


def test_cache_invalidates_when_mtime_changes(tmp_path, monkeypatch):
    VSPAeroParser._parse_cache.clear()
    lod_path = _write_sample_lod(tmp_path)
    parser = VSPAeroParser(lod_path)

    mtime_values = iter([1_000_000_000, 2_000_000_000])

    def fake_stat(_path):
        return SimpleNamespace(st_mtime_ns=next(mtime_values))

    monkeypatch.setattr(vsp_aero_module.os, "stat", fake_stat)

    first = parser.parse()
    second = parser.parse()

    assert len(second) > 0
    assert second is not first
