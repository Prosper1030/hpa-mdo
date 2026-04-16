"""Unit tests for hpa_mdo.hifi.aswing_runner (M-ASWING).

ASWING installation is NOT required.  The runner tests cover:
  - find_aswing() binary detection
  - run_aswing() with missing binary (graceful error)
  - stdout parser for each regex pattern
  - station-table fallback parser
  - Integration: build .asw seed + run reports correct keys

Tests that actually invoke ASWING are skipped unless the binary is
available on PATH or configured.
"""
from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hpa_mdo.hifi.aswing_runner import (
    _parse_stdout,
    _RESULT_TEMPLATE,
    find_aswing,
    run_aswing,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result() -> dict:
    return dict(_RESULT_TEMPLATE)


# ---------------------------------------------------------------------------
# find_aswing
# ---------------------------------------------------------------------------

class TestFindAswing:
    def test_returns_none_when_not_on_path(self, monkeypatch):
        monkeypatch.setenv("PATH", "")
        import shutil
        with patch.object(shutil, "which", return_value=None):
            assert find_aswing(None) is None

    def test_returns_path_when_on_path(self):
        with patch("shutil.which", return_value="/usr/local/bin/aswing"):
            result = find_aswing(None)
        assert result == "/usr/local/bin/aswing"

    def test_config_binary_takes_precedence(self, tmp_path):
        fake_bin = tmp_path / "aswing"
        fake_bin.write_text("#!/bin/sh\n", encoding="utf-8")

        cfg = MagicMock()
        cfg.hi_fidelity.aswing.binary = str(fake_bin)
        result = find_aswing(cfg)
        assert result == str(fake_bin)

    def test_config_binary_missing_falls_back_to_path(self, tmp_path):
        cfg = MagicMock()
        cfg.hi_fidelity.aswing.binary = str(tmp_path / "nonexistent_aswing")
        with patch("shutil.which", return_value="/opt/bin/aswing"):
            result = find_aswing(cfg)
        assert result == "/opt/bin/aswing"


# ---------------------------------------------------------------------------
# run_aswing — missing binary
# ---------------------------------------------------------------------------

class TestRunAswingMissingBinary:
    def test_returns_error_dict_not_raise(self):
        cfg = MagicMock()
        cfg.hi_fidelity.aswing.binary = None
        cfg.hi_fidelity.aswing.timeout_s = 60
        cfg.hi_fidelity.aswing.vinf_mps = None
        cfg.flight.velocity = 6.5

        with patch("shutil.which", return_value=None):
            result = run_aswing(Path("/tmp/fake.asw"), cfg)

        assert result["error"] is not None
        assert "not found" in result["error"].lower()
        assert result["converged"] is False
        assert result["tip_deflection_m"] is None

    def test_all_expected_keys_present(self):
        cfg = MagicMock()
        cfg.hi_fidelity.aswing.binary = None
        cfg.hi_fidelity.aswing.timeout_s = 60
        cfg.hi_fidelity.aswing.vinf_mps = None
        cfg.flight.velocity = 6.5

        with patch("shutil.which", return_value=None):
            result = run_aswing(Path("/tmp/fake.asw"), cfg)

        expected_keys = {
            "tip_deflection_m", "tip_twist_deg", "CL_trim",
            "alpha_trim_deg", "CM_trim", "converged", "stdout", "error",
        }
        assert set(result.keys()) == expected_keys


# ---------------------------------------------------------------------------
# _parse_stdout — unit tests on regex patterns
# ---------------------------------------------------------------------------

class TestParseStdout:
    def test_cl_and_alpha_parsed(self):
        stdout = "  CLtot =   1.2352    alpha =  10.98  deg\n"
        result = _make_result()
        _parse_stdout(stdout, result)
        assert result["CL_trim"] == pytest.approx(1.2352, abs=1e-4)
        assert result["alpha_trim_deg"] == pytest.approx(10.98, abs=1e-4)

    def test_cm_parsed(self):
        stdout = "  CMtot =  -0.0821\n"
        result = _make_result()
        _parse_stdout(stdout, result)
        assert result["CM_trim"] == pytest.approx(-0.0821, abs=1e-4)

    def test_tip_deflection_explicit_line(self):
        stdout = "  Tip deflection  uz =  2.341 m   twist = -0.501 deg\n"
        result = _make_result()
        _parse_stdout(stdout, result)
        assert result["tip_deflection_m"] == pytest.approx(2.341, abs=1e-3)
        assert result["tip_twist_deg"] == pytest.approx(-0.501, abs=1e-3)

    def test_converged_flag_detected(self):
        stdout = "Trim converged after 12 iterations\n"
        result = _make_result()
        _parse_stdout(stdout, result)
        assert result["converged"] is True

    def test_converged_not_set_on_empty(self):
        result = _make_result()
        _parse_stdout("", result)
        assert result["converged"] is False
        assert result["CL_trim"] is None

    def test_negative_values_parsed(self):
        stdout = "  CLtot =  -0.1234    alpha =  -3.50  deg\n"
        result = _make_result()
        _parse_stdout(stdout, result)
        assert result["CL_trim"] == pytest.approx(-0.1234, abs=1e-4)
        assert result["alpha_trim_deg"] == pytest.approx(-3.50, abs=1e-4)

    def test_scientific_notation_parsed(self):
        stdout = "  CLtot =  1.2352e+00    alpha =  1.098e+01  deg\n"
        result = _make_result()
        _parse_stdout(stdout, result)
        assert result["CL_trim"] == pytest.approx(1.2352, abs=1e-4)
        assert result["alpha_trim_deg"] == pytest.approx(10.98, abs=1e-3)


# ---------------------------------------------------------------------------
# _parse_stdout — station table fallback
# ---------------------------------------------------------------------------

class TestStationTableParser:
    _TABLE = textwrap.dedent("""\
        iw   t      X      Y      Z     Chord  Twist   CL
        1  0.000  0.000  0.000  0.000  1.300   0.000  0.800
        1  4.500  0.079  4.500  0.085  1.300  -0.150  0.750
        1 16.500  0.340 16.490  2.341  0.435  -0.501  0.320

    """)

    def test_tip_z_extracted(self):
        result = _make_result()
        _parse_stdout(self._TABLE, result)
        assert result["tip_deflection_m"] == pytest.approx(2.341, abs=1e-3)

    def test_tip_twist_extracted(self):
        result = _make_result()
        _parse_stdout(self._TABLE, result)
        assert result["tip_twist_deg"] == pytest.approx(-0.501, abs=1e-3)

    def test_converged_set_when_table_found(self):
        result = _make_result()
        _parse_stdout(self._TABLE, result)
        assert result["converged"] is True

    def test_explicit_line_wins_over_table(self):
        # Explicit line has priority; table should not overwrite.
        stdout = (
            "  Tip deflection  uz =  9.999 m   twist = 1.234 deg\n"
            + self._TABLE
        )
        result = _make_result()
        _parse_stdout(stdout, result)
        assert result["tip_deflection_m"] == pytest.approx(9.999, abs=1e-3)
        assert result["tip_twist_deg"] == pytest.approx(1.234, abs=1e-3)

    def test_multi_table_uses_last_row_of_last_table(self):
        """If ASWING prints multiple iteration tables, use the last row of the
        last table (final converged solution)."""
        stdout = textwrap.dedent("""\
            iw   t      X      Y      Z     Chord  Twist   CL
            1  0.000  0.000  0.000  0.000  1.300   0.000  0.800
            1 16.500  0.340 16.490  1.111  0.435  -0.100  0.320

            iw   t      X      Y      Z     Chord  Twist   CL
            1  0.000  0.000  0.000  0.000  1.300   0.000  0.800
            1 16.500  0.340 16.490  2.341  0.435  -0.501  0.320

        """)
        result = _make_result()
        _parse_stdout(stdout, result)
        # Should pick up the last table's last row
        assert result["tip_deflection_m"] == pytest.approx(2.341, abs=1e-3)


# ---------------------------------------------------------------------------
# Integration: .asw seed + report writing (no ASWING binary needed)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not Path("/Volumes/Samsung SSD/hpa-mdo/data/blackcat_004_full.avl").exists(),
    reason="AVL file not found — skip integration test",
)
class TestAswingSeedGeneration:
    """Verify that build_aswing_asw (via export_aswing) produces a valid seed."""

    REPO = Path(__file__).resolve().parents[1]

    def test_asw_seed_written(self, tmp_path):
        from hpa_mdo.aero.aswing_exporter import export_aswing
        from hpa_mdo.core import load_config
        from hpa_mdo.core.materials import MaterialDB

        cfg = load_config(
            self.REPO / "configs" / "blackcat_004.yaml",
            local_paths_path=tmp_path / "missing_local_paths.yaml",
        )
        mat_db = MaterialDB(self.REPO / "data" / "materials.yaml")
        avl_path = self.REPO / "data" / "blackcat_004_full.avl"

        out = export_aswing(avl_path, cfg, tmp_path / "test.asw", materials_db=mat_db)
        text = out.read_text(encoding="utf-8")

        assert "Name" in text
        assert "Beam" in text
        assert "EIcc" in text
        assert "GJ" in text

    def test_run_aswing_without_binary_returns_error(self, tmp_path):
        """Even without ASWING installed, run_aswing must return a dict."""
        from hpa_mdo.aero.aswing_exporter import export_aswing
        from hpa_mdo.core import load_config
        from hpa_mdo.core.materials import MaterialDB

        cfg = load_config(
            self.REPO / "configs" / "blackcat_004.yaml",
            local_paths_path=tmp_path / "missing_local_paths.yaml",
        )
        mat_db = MaterialDB(self.REPO / "data" / "materials.yaml")
        avl_path = self.REPO / "data" / "blackcat_004_full.avl"
        asw_path = export_aswing(
            avl_path, cfg, tmp_path / "test.asw", materials_db=mat_db
        )

        with patch("shutil.which", return_value=None):
            result = run_aswing(asw_path, cfg, aswing_binary=None)

        assert isinstance(result, dict)
        assert "error" in result
        assert result["error"] is not None
