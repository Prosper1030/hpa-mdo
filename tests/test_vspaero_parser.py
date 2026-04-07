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
