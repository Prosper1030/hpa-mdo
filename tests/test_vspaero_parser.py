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


# OpenVSP 3.45.3 emits a 60+ column .lod table that begins with
#   `Iter VortexSheet TrailVort Xavg Yavg Zavg dSpan SoverB Chord dArea V/Vref Cl Cd Cs ...`
# The parser must identify columns by name so Zavg is not mistaken for Chord.
_MODERN_HEADER_COLUMNS = [
    "Iter", "VortexSheet", "TrailVort",
    "Xavg", "Yavg", "Zavg", "dSpan", "SoverB", "Chord", "dArea",
    "V/Vref", "Cl", "Cd", "Cs",
    "Clo", "Cdo", "Cso", "Cli", "Cdi", "Csi",
    "Cx", "Cy", "Cz", "Cxo", "Cyo", "Czo", "Cxi", "Cyi", "Czi",
    "Cmx", "Cmy", "Cmz", "Cmxo", "Cmyo", "Cmzo", "Cmxi", "Cmyi", "Cmzi",
    "StallFact", "IsARotor",
    "Diameter", "roverR", "RPM",
    "Thrust", "Thrusto", "Thrusti",
    "Power", "Powero", "Poweri",
    "Moment", "Momento", "Momenti",
    "J", "CT", "CQ", "CP", "ETAP",
    "CT_h", "CQ_h", "CP_h", "FOM", "Angle",
]


def _modern_lod_row(
    component: int,
    strip_idx: int,
    xavg: float,
    yavg: float,
    zavg: float,
    chord: float,
    cl: float,
    cd: float,
    cmy: float,
) -> str:
    values = [0.0] * len(_MODERN_HEADER_COLUMNS)
    values[0] = 5  # Iter
    values[1] = component  # VortexSheet
    values[2] = strip_idx  # TrailVort
    values[3] = xavg
    values[4] = yavg
    values[5] = zavg
    values[8] = chord
    values[10] = 1.0  # V/Vref
    values[11] = cl
    values[12] = cd
    values[30] = cmy
    return " ".join(f"{v:.6f}" for v in values)


def _modern_lod_block() -> str:
    header_columns = " ".join(_MODERN_HEADER_COLUMNS)
    # Values are representative of a half-wing strip on a high-aspect-ratio
    # design: positive chord, y increasing from root to tip, Zavg spanning a
    # small negative-to-positive range to expose the old Zavg-as-Chord bug.
    data_rows = "\n".join(
        [
            _modern_lod_row(1, 1, 0.68, 0.60, -0.46, 1.20, 0.40, 0.023, -0.090),
            _modern_lod_row(1, 2, 0.74, 3.00, -0.10, 1.10, 0.45, 0.022, -0.085),
            _modern_lod_row(1, 3, 0.80, 8.00, 0.25, 1.00, 0.50, 0.021, -0.080),
            _modern_lod_row(1, 4, 0.90, 13.00, 0.53, 0.80, 0.46, 0.019, -0.072),
            _modern_lod_row(1, 5, 1.00, 16.00, 0.78, 0.48, 0.38, 0.028, -0.060),
            # Symmetric left-half rows (negative y) to verify the right-half mask
            _modern_lod_row(1, 6, 0.68, -0.60, -0.46, 1.20, 0.40, 0.023, -0.090),
            _modern_lod_row(1, 7, 1.00, -16.00, 0.78, 0.48, 0.38, 0.028, -0.060),
        ]
    )
    return "\n".join(
        [
            "***********************",
            "# Name                   Value      Units",
            "Sref_                  28.6275000 Lunit^2",
            "Cref_                   0.8675000 Lunit",
            "Bref_                  33.0000000 Lunit",
            "Mach_                   0.0010000 no_unit",
            "AoA_                    3.5000000 deg",
            "Beta_                   0.0000000 deg",
            "Rho_                    1.2250000 Munit/Lunit^3",
            "Vinf_                   6.5000000 Lunit/Tunit",
            "",
            header_columns,
            data_rows,
        ]
    )


def test_parse_modern_openvsp_3_45_3_format(tmp_path):
    VSPAeroParser._parse_cache.clear()
    lod_path = tmp_path / "modern_format.lod"
    lod_path.write_text(_modern_lod_block() + "\n", encoding="utf-8")

    cases = VSPAeroParser(lod_path).parse()

    assert len(cases) == 1
    case = cases[0]
    # Right half-span only, sorted ascending.
    np.testing.assert_allclose(case.y, np.array([0.60, 3.00, 8.00, 13.00, 16.00]))
    # Chord must be strictly positive: the whole point of this regression is
    # that Zavg (which dips to -0.46 m in the fixture) is no longer mis-read
    # as Chord.
    assert np.all(case.chord > 0.0)
    np.testing.assert_allclose(case.chord, np.array([1.20, 1.10, 1.00, 0.80, 0.48]))
    np.testing.assert_allclose(case.cl, np.array([0.40, 0.45, 0.50, 0.46, 0.38]))
    np.testing.assert_allclose(case.cd, np.array([0.023, 0.022, 0.021, 0.019, 0.028]))
    np.testing.assert_allclose(case.cm, np.array([-0.090, -0.085, -0.080, -0.072, -0.060]))
    assert case.aoa_deg == pytest.approx(3.5)
    assert case.velocity == pytest.approx(6.5)


def test_parse_modern_openvsp_3_45_3_format_component_filter(tmp_path):
    VSPAeroParser._parse_cache.clear()
    # Build a two-component variant: VortexSheet=1 (wing) + VortexSheet=2 (tail).
    header_columns = " ".join(_MODERN_HEADER_COLUMNS)
    rows = "\n".join(
        [
            _modern_lod_row(1, 1, 0.8, 1.00, 0.0, 1.10, 0.50, 0.02, -0.08),
            _modern_lod_row(1, 2, 0.8, 5.00, 0.0, 0.90, 0.45, 0.02, -0.07),
            _modern_lod_row(2, 1, 3.0, 2.00, 1.5, 0.40, 0.10, 0.01, -0.02),
        ]
    )
    content = "\n".join(
        [
            "***********************",
            "# Name Value Units",
            "Sref_ 28.6275 Lunit^2",
            "AoA_ 2.0 deg",
            "Rho_ 1.2250 Munit/Lunit^3",
            "Vinf_ 6.5 Lunit/Tunit",
            "",
            header_columns,
            rows,
        ]
    )
    lod_path = tmp_path / "modern_two_component.lod"
    lod_path.write_text(content + "\n", encoding="utf-8")

    wing_only = VSPAeroParser(lod_path, component_ids=[1]).parse()
    tail_only = VSPAeroParser(lod_path, component_ids=[2]).parse()

    assert len(wing_only) == 1
    np.testing.assert_allclose(wing_only[0].y, np.array([1.00, 5.00]))
    np.testing.assert_allclose(wing_only[0].chord, np.array([1.10, 0.90]))

    assert len(tail_only) == 1
    np.testing.assert_allclose(tail_only[0].y, np.array([2.00]))
    np.testing.assert_allclose(tail_only[0].chord, np.array([0.40]))


def test_parse_real_candidate_rerun_lod_has_strictly_positive_chord():
    """Smoke: if a real OpenVSP 3.45.3-produced .lod from the Track P rerun
    is present, parsing it must return chord > 0 and a half-span y range.
    Skips silently on fresh checkouts without the artifact."""
    candidate_lod = Path(
        "/Volumes/Samsung SSD/hpa-mdo/output/rib_smoke_track_p/off/"
        "target_20.0kg/candidate_aero/black_cat_004.lod"
    )
    if not candidate_lod.exists():
        pytest.skip(f"candidate-rerun .lod artifact not present: {candidate_lod}")
    VSPAeroParser._parse_cache.clear()

    cases = VSPAeroParser(candidate_lod).parse()

    assert cases, "parser returned no AoA cases"
    for case in cases:
        assert np.all(case.chord > 0.0), "chord contains non-positive values"
        assert case.y.size > 0
        assert case.y.min() >= 0.0, "right-half-span mask failed"
        # Half-span of black_cat_004 is ~16.5 m; reject if we only see a tiny
        # y range (the old bug truncated it to ~7.7 m because Xavg was being
        # treated as Yavg).
        assert case.y.max() > 10.0, (
            f"parsed y range looks truncated (max={case.y.max():.2f} m); "
            "did the parser fall back to the legacy column layout?"
        )
