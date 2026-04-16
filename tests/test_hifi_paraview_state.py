"""Unit tests for hpa_mdo.hifi.paraview_state (M-HF4).

No ParaView installation required — we only validate the generated
Python script content and the file-discovery logic.
"""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from hpa_mdo.hifi.paraview_state import discover_frd_files, make_pvpython_script


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_frd_dir(tmp_path: Path) -> Path:
    """Create a directory with synthetic .frd stubs."""
    hifi = tmp_path / "hifi"
    hifi.mkdir()
    (hifi / "static.frd").write_text("# static result stub\n", encoding="utf-8")
    (hifi / "buckle_mode01.frd").write_text("# buckle mode 1\n", encoding="utf-8")
    (hifi / "buckle_mode02.frd").write_text("# buckle mode 2\n", encoding="utf-8")
    (hifi / "buckle_mode03.frd").write_text("# buckle mode 3\n", encoding="utf-8")
    return hifi


# ---------------------------------------------------------------------------
# discover_frd_files tests
# ---------------------------------------------------------------------------

class TestDiscoverFrdFiles:
    def test_finds_static_and_buckle(self, fake_frd_dir: Path):
        static, buckles = discover_frd_files(fake_frd_dir)
        assert static is not None
        assert static.name == "static.frd"
        assert len(buckles) == 3
        assert buckles[0].name == "buckle_mode01.frd"

    def test_buckle_sorted(self, fake_frd_dir: Path):
        _, buckles = discover_frd_files(fake_frd_dir)
        names = [b.name for b in buckles]
        assert names == sorted(names)

    def test_missing_dir_returns_none_empty(self, tmp_path: Path):
        static, buckles = discover_frd_files(tmp_path / "nonexistent")
        assert static is None
        assert buckles == []

    def test_static_only(self, tmp_path: Path):
        hifi = tmp_path / "static_only"
        hifi.mkdir()
        (hifi / "static.frd").write_text("x", encoding="utf-8")
        static, buckles = discover_frd_files(hifi)
        assert static is not None
        assert buckles == []

    def test_empty_dir(self, tmp_path: Path):
        hifi = tmp_path / "empty"
        hifi.mkdir()
        static, buckles = discover_frd_files(hifi)
        assert static is None
        assert buckles == []


# ---------------------------------------------------------------------------
# make_pvpython_script generation tests
# ---------------------------------------------------------------------------

class TestMakePvpythonScript:
    def _gen(self, fake_frd_dir, tmp_path, **kwargs) -> tuple[Path, str]:
        static, buckles = discover_frd_files(fake_frd_dir)
        all_frds = [static] + buckles
        out = tmp_path / "vis.py"
        path = make_pvpython_script(all_frds, out, **kwargs)
        content = path.read_text(encoding="utf-8")
        return path, content

    def test_file_created(self, fake_frd_dir, tmp_path):
        path, _ = self._gen(fake_frd_dir, tmp_path)
        assert path.exists()
        assert path.suffix == ".py"

    def test_script_is_valid_python(self, fake_frd_dir, tmp_path):
        """Generated script must parse without SyntaxError."""
        _, content = self._gen(fake_frd_dir, tmp_path)
        # ast.parse validates syntax without execution
        try:
            ast.parse(content)
        except SyntaxError as exc:
            pytest.fail(f"Generated script has a syntax error: {exc}")

    def test_static_frd_path_present(self, fake_frd_dir, tmp_path):
        _, content = self._gen(fake_frd_dir, tmp_path)
        static_name = "static.frd"
        assert static_name in content

    def test_buckle_frd_paths_present(self, fake_frd_dir, tmp_path):
        _, content = self._gen(fake_frd_dir, tmp_path)
        for i in range(1, 4):
            assert f"buckle_mode0{i}.frd" in content

    def test_warp_scale_in_script(self, fake_frd_dir, tmp_path):
        _, content = self._gen(fake_frd_dir, tmp_path, warp_scale=25.0)
        assert "25.0" in content

    def test_show_modes_limits_buckle_entries(self, fake_frd_dir, tmp_path):
        """show_modes=1 should only include the first buckle mode."""
        _, content = self._gen(fake_frd_dir, tmp_path, show_modes=1)
        assert "buckle_mode01.frd" in content
        assert "buckle_mode03.frd" not in content

    def test_span_present(self, fake_frd_dir, tmp_path):
        _, content = self._gen(fake_frd_dir, tmp_path, span_m=12.0)
        assert "12.0" in content

    def test_paraview_imports_present(self, fake_frd_dir, tmp_path):
        _, content = self._gen(fake_frd_dir, tmp_path)
        assert "from paraview.simple import" in content
        assert "OpenDataFile" in content
        assert "WarpByVector" in content
        assert "RenderAllViews" in content

    def test_von_mises_colormap_setup_present(self, fake_frd_dir, tmp_path):
        _, content = self._gen(fake_frd_dir, tmp_path)
        assert "_setup_vonmises_colormap" in content

    def test_displacement_colormap_setup_present(self, fake_frd_dir, tmp_path):
        _, content = self._gen(fake_frd_dir, tmp_path)
        assert "_setup_displacement_colormap" in content

    def test_camera_setup_present(self, fake_frd_dir, tmp_path):
        _, content = self._gen(fake_frd_dir, tmp_path)
        assert "_set_camera" in content
        assert "CameraFocalPoint" in content

    def test_no_buckle_produces_comment(self, tmp_path):
        """Static-only run should note no buckling results."""
        static_frd = tmp_path / "static.frd"
        static_frd.write_text("x", encoding="utf-8")
        out = tmp_path / "vis.py"
        make_pvpython_script([static_frd], out)
        content = out.read_text(encoding="utf-8")
        assert "No buckling results found" in content

    def test_empty_frd_list_produces_valid_script(self, tmp_path):
        out = tmp_path / "vis.py"
        make_pvpython_script([], out)
        content = out.read_text(encoding="utf-8")
        ast.parse(content)   # must not raise

    def test_output_dir_created_if_missing(self, fake_frd_dir, tmp_path):
        static, buckles = discover_frd_files(fake_frd_dir)
        out = tmp_path / "nested" / "deep" / "vis.py"
        make_pvpython_script([static] + buckles, out)
        assert out.exists()

    def test_golden_regression(self, fake_frd_dir, tmp_path):
        """Script must contain all key sections in the correct order."""
        _, content = self._gen(fake_frd_dir, tmp_path, warp_scale=10.0, show_modes=6)
        # Section order check
        header_pos  = content.find("_DisableFirstRenderCameraReset")
        static_pos  = content.find("Static result")
        buckle_pos  = content.find("Buckling modes")
        footer_pos  = content.find("RenderAllViews()")
        assert header_pos  < static_pos  < buckle_pos < footer_pos, (
            "Script sections are out of expected order"
        )
