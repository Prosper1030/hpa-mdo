from __future__ import annotations

from pathlib import Path
import shutil

from hpa_mdo.core import load_config
from hpa_mdo.hifi import gmsh_runner
from hpa_mdo.hifi.gmsh_runner import find_gmsh, mesh_step_to_inp


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "configs" / "blackcat_004.yaml"


def _cfg(tmp_path: Path):
    return load_config(CONFIG_PATH, local_paths_path=tmp_path / "missing_local_paths.yaml")


def test_find_gmsh_returns_none_when_disabled(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    cfg.hi_fidelity.gmsh.enabled = False
    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/local/bin/gmsh")

    assert find_gmsh(cfg) is None


def test_find_gmsh_uses_configured_binary(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    gmsh = tmp_path / "gmsh"
    gmsh.write_text("#!/bin/sh\n", encoding="utf-8")
    cfg.hi_fidelity.gmsh.enabled = True
    cfg.hi_fidelity.gmsh.binary = str(gmsh)

    assert find_gmsh(cfg) == str(gmsh.resolve())


def test_mesh_step_skips_gracefully_when_gmsh_missing(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    cfg.hi_fidelity.gmsh.enabled = True
    monkeypatch.setattr(gmsh_runner, "find_gmsh", lambda _cfg: None)

    result = mesh_step_to_inp(tmp_path / "missing.step", tmp_path / "out.inp", cfg)

    assert result is None


def test_mesh_step_invokes_gmsh_cli(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    cfg.hi_fidelity.gmsh.enabled = True
    cfg.hi_fidelity.gmsh.mesh_size_m = 0.123
    step_path = tmp_path / "part.step"
    out_path = tmp_path / "mesh.inp"
    step_path.write_text("STEP", encoding="utf-8")
    monkeypatch.setattr(gmsh_runner, "find_gmsh", lambda _cfg: "/opt/bin/gmsh")

    def fake_run(cmd, **kwargs):
        out_path.write_text("*NODE\n", encoding="utf-8")
        assert cmd == [
            "/opt/bin/gmsh",
            str(step_path),
            "-3",
            "-format",
            "inp",
            "-order",
            "1",
            "-clmax",
            "0.123",
            "-o",
            str(out_path),
        ]
        assert kwargs["check"] is False
        assert kwargs["capture_output"] is True
        assert kwargs["timeout"] == 600
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(gmsh_runner.subprocess, "run", fake_run)

    assert mesh_step_to_inp(step_path, out_path, cfg) == out_path
