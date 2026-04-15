from __future__ import annotations

from pathlib import Path
import shutil

from hpa_mdo.core import load_config
from hpa_mdo.hifi import gmsh_runner
from hpa_mdo.hifi.gmsh_runner import (
    NamedPoint,
    annotate_inp_with_named_points,
    find_gmsh,
    mesh_step_to_inp,
    parse_nset_from_inp,
)


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


# --- NamedPoint / NSET annotation ---------------------------------------


_SAMPLE_INP = """\
*HEADING
test
*NODE
1, 0.0, 0.0, 0.0
2, 0.0, 1.5, 0.0
3, 0.0, 4.5, 0.0
4, 0.0, 16.5, 0.0
*ELEMENT, TYPE=C3D4, ELSET=EALL
1, 1, 2, 3, 4
"""


def test_annotate_inp_writes_nset_blocks(tmp_path: Path) -> None:
    inp = tmp_path / "mesh.inp"
    inp.write_text(_SAMPLE_INP, encoding="utf-8")

    written = annotate_inp_with_named_points(
        inp,
        [
            NamedPoint("ROOT", (0.0, 0.0, 0.0)),
            NamedPoint("TIP", (0.0, 16.5, 0.0)),
            NamedPoint("WIRE_1", (0.0, 1.5, 0.0)),
        ],
        default_tol_m=1.0e-3,
    )
    assert written == ["ROOT", "TIP", "WIRE_1"]

    text = inp.read_text(encoding="utf-8")
    assert "*NSET, NSET=ROOT" in text
    assert "*NSET, NSET=TIP" in text
    assert "*NSET, NSET=WIRE_1" in text
    # NSET blocks must sit before the first *ELEMENT block so CalculiX
    # parses them in the part section.
    assert text.index("*NSET, NSET=ROOT") < text.index("*ELEMENT")

    nsets = parse_nset_from_inp(inp)
    assert nsets["ROOT"] == [1]
    assert nsets["TIP"] == [4]
    assert nsets["WIRE_1"] == [2]


def test_annotate_inp_skips_out_of_tolerance(tmp_path: Path, capsys) -> None:
    inp = tmp_path / "mesh.inp"
    inp.write_text(_SAMPLE_INP, encoding="utf-8")

    written = annotate_inp_with_named_points(
        inp,
        [NamedPoint("MISSING", (10.0, 0.0, 0.0), tol_m=1.0e-3)],
        default_tol_m=1.0e-3,
    )
    assert written == []
    captured = capsys.readouterr()
    assert "NamedPoint 'MISSING' unmatched" in captured.out
    assert "*NSET, NSET=MISSING" not in inp.read_text(encoding="utf-8")


def test_mesh_step_annotates_named_points(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    cfg.hi_fidelity.gmsh.enabled = True
    cfg.hi_fidelity.gmsh.mesh_size_m = 0.05
    cfg.hi_fidelity.gmsh.point_tol_m = 1.0e-3
    step_path = tmp_path / "part.step"
    out_path = tmp_path / "mesh.inp"
    step_path.write_text("STEP", encoding="utf-8")
    monkeypatch.setattr(gmsh_runner, "find_gmsh", lambda _cfg: "/opt/bin/gmsh")

    def fake_run(cmd, **kwargs):
        out_path.write_text(_SAMPLE_INP, encoding="utf-8")
        return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(gmsh_runner.subprocess, "run", fake_run)

    assert (
        mesh_step_to_inp(
            step_path,
            out_path,
            cfg,
            named_points=[
                NamedPoint("ROOT", (0.0, 0.0, 0.0)),
                NamedPoint("TIP", (0.0, 16.5, 0.0)),
            ],
        )
        == out_path
    )
    nsets = parse_nset_from_inp(out_path)
    assert nsets.get("ROOT") == [1]
    assert nsets.get("TIP") == [4]
