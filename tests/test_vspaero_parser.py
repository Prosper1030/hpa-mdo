from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hpa_mdo.aero.vsp_aero import VSPAeroParser
from hpa_mdo.core.config import load_config


def _blackcat_lod_path() -> Path | None:
    repo_root = Path(__file__).resolve().parents[1]
    cfg = load_config(repo_root / "configs" / "blackcat_004.yaml")
    return cfg.io.vsp_lod


def test_parse_returns_list_of_spanwise_loads():
    lod_path = _blackcat_lod_path()
    if lod_path is None or not lod_path.exists():
        pytest.skip(f"VSPAero .lod not found: {lod_path}")

    parser = VSPAeroParser(lod_path)
    cases = parser.parse()

    assert isinstance(cases, list)
    assert len(cases) > 0
    for case in cases:
        assert hasattr(case, "y")
        assert hasattr(case, "cl")
        assert hasattr(case, "chord")
        assert hasattr(case, "aoa_deg")


def test_parse_handles_multiple_aoa_cases():
    lod_path = _blackcat_lod_path()
    if lod_path is None or not lod_path.exists():
        pytest.skip(f"VSPAero .lod not found: {lod_path}")

    parser = VSPAeroParser(lod_path)
    cases = parser.parse()
    if len(cases) < 2:
        pytest.skip("Need at least two AoA cases in .lod to validate multi-case parsing.")

    unique_aoa = {round(case.aoa_deg, 8) for case in cases}
    if len(unique_aoa) < 2:
        pytest.skip("Parsed cases do not contain distinct AoA values.")

    first, second = cases[0], cases[1]
    assert first is not second
    assert not np.shares_memory(first.y, second.y)
    assert not np.shares_memory(first.cl, second.cl)


def test_parse_raises_on_missing_file(tmp_path):
    missing = tmp_path / "missing_case.lod"
    parser = VSPAeroParser(missing)

    with pytest.raises((FileNotFoundError, ValueError)):
        parser.parse()


def test_parse_header_extracts_reference_values():
    header = "\n".join(
        [
            "Sref_ 35.1750000 Lunit^2",
            "Bref_ 33.0000000 Lunit",
            "Cref_ 1.1000000 Lunit",
            "Mach_ 0.0300000",
            "AoA_ 3.5000000 Deg",
            "Rho_ 1.2250000 kg/m^3",
            "Vinf_ 6.5000000 m/s",
        ]
    )

    ref = VSPAeroParser._parse_header(header)

    assert ref["sref"] == pytest.approx(35.175)
    assert ref["bref"] == pytest.approx(33.0)
    assert ref["cref"] == pytest.approx(1.1)
    assert ref["aoa"] == pytest.approx(3.5)


def _mock_lod_block() -> str:
    return "\n".join(
        [
            "Sref_ 35.1750000 Lunit^2",
            "Bref_ 33.0000000 Lunit",
            "Cref_ 1.1000000 Lunit",
            "AoA_ 3.0000000 Deg",
            "Rho_ 1.2250000 kg/m^3",
            "Vinf_ 10.0000000 m/s",
            "Wing S Xavg Yavg Zavg Chord V/Vref Cl Cd Cs Cx Cy Cz Cmx Cmy Cmz",
            "1 1.0 0.0 0.50 0.0 1.0 1.0 0.50 0.01 0.0 0.0 0.0 0.0 0.0 0.020 0.0",
            "2 1.0 0.0 1.00 0.0 0.9 1.0 0.40 0.01 0.0 0.0 0.0 0.0 0.0 0.015 0.0",
            "1 1.0 0.0 -0.50 0.0 1.0 1.0 0.45 0.01 0.0 0.0 0.0 0.0 0.0 0.018 0.0",
        ]
    )


def test_component_filter_selects_only_requested_component(tmp_path):
    VSPAeroParser._parse_cache.clear()
    lod_path = tmp_path / "mock_components.lod"
    lod_path.write_text(_mock_lod_block() + "\n", encoding="utf-8")

    all_components = VSPAeroParser(lod_path).parse()
    wing_only = VSPAeroParser(lod_path, component_ids=[1]).parse()
    tail_only = VSPAeroParser(lod_path, component_ids=[2]).parse()

    assert len(all_components) == 1
    assert len(wing_only) == 1
    assert len(tail_only) == 1
    np.testing.assert_allclose(all_components[0].y, np.array([0.5, 1.0]))
    np.testing.assert_allclose(wing_only[0].y, np.array([0.5]))
    np.testing.assert_allclose(tail_only[0].y, np.array([1.0]))


def test_parser_warns_when_multiple_components_without_filter(tmp_path, caplog):
    VSPAeroParser._parse_cache.clear()
    lod_path = tmp_path / "mock_components_warning.lod"
    lod_path.write_text(_mock_lod_block() + "\n", encoding="utf-8")

    with caplog.at_level("WARNING"):
        parser = VSPAeroParser(lod_path)
        parser.parse()

    assert "multiple component IDs" in caplog.text
