from __future__ import annotations

from pathlib import Path

import numpy as np

from hpa_mdo.core import load_config
from hpa_mdo.hifi import structural_check


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "configs" / "blackcat_004.yaml"

MESH_WITH_NSETS = """*NODE
1, 0.0, 0.0, 0.0
2, 0.0, 1.5, 0.0
3, 0.0, 4.5, 0.0
4, 0.0, 16.5, 0.0
*NSET, NSET=ROOT
1
*NSET, NSET=TIP
4
*ELEMENT, TYPE=C3D4
10, 1, 2, 3, 4
"""


def _cfg(tmp_path: Path):
    return load_config(CONFIG_PATH, local_paths_path=tmp_path / "missing_local_paths.yaml")


def test_parse_optimization_summary_extracts_tip_and_buckling(tmp_path: Path) -> None:
    summary = tmp_path / "optimization_summary.txt"
    summary.write_text(
        "\n".join(
            [
                "HPA-MDO Spar Optimization Summary",
                "  Tip deflection  : 2500.00 mm  (2.50000 m) / MAX: 2500.0 mm (OK)",
                "  Buckling index  : -0.80128  (SAFE)",
            ]
        ),
        encoding="utf-8",
    )

    metrics = structural_check.parse_optimization_summary(summary)

    assert metrics["tip_deflection_m"] == 2.5
    assert metrics["buckling_index"] == -0.80128


def test_run_structural_check_uses_existing_mesh_and_writes_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    hifi_dir = output_dir / "hifi"
    summary = output_dir / "optimization_summary.txt"
    summary.write_text(
        "\n".join(
            [
                "HPA-MDO Spar Optimization Summary",
                "  Tip deflection  : 2500.00 mm  (2.50000 m)",
                "  Buckling index  : -0.80000",
            ]
        ),
        encoding="utf-8",
    )
    mesh = hifi_dir / "wing_cruise.inp"
    hifi_dir.mkdir()
    mesh.write_text(MESH_WITH_NSETS, encoding="utf-8")

    cfg.io.output_dir = str(output_dir)
    monkeypatch.setattr(structural_check, "load_config", lambda _path: cfg)

    def fake_run_static(inp_path, _cfg):
        inp_path = Path(inp_path)
        frd = inp_path.with_suffix(".frd")
        dat = inp_path.with_suffix(".dat")
        frd.write_text("stub", encoding="utf-8")
        dat.write_text("stub", encoding="utf-8")
        return {
            "frd": frd,
            "dat": dat,
            "returncode": 0,
            "stdout": "",
            "stderr": "",
        }

    monkeypatch.setattr(structural_check, "run_static", fake_run_static)
    monkeypatch.setattr(
        structural_check,
        "parse_displacement",
        lambda _path: np.asarray(
            [
                [1.0, 0.0, 0.0, 0.0],
                [4.0, 0.0, 0.0, -2.5],
            ]
        ),
    )
    monkeypatch.setattr(structural_check, "parse_buckle_eigenvalues", lambda _path: [5.5, 7.2])

    result = structural_check.run_structural_check(
        config_path=CONFIG_PATH,
        summary_path=summary,
        mesh_path=mesh,
        hifi_dir=hifi_dir,
    )

    report_text = result.report_path.read_text(encoding="utf-8")
    assert result.overall_status == "PASS"
    assert result.static.status == "PASS"
    assert result.buckle.status == "PASS"
    assert result.paraview_script_path is not None
    assert result.paraview_script_path.exists()
    assert "Overall status: PASS" in report_text
    assert "Static tip-deflection check completed." in report_text
    assert "Buckling check completed." in report_text


def test_run_structural_check_skips_when_no_mesh_or_step(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    cfg.io.output_dir = str(output_dir)
    monkeypatch.setattr(structural_check, "load_config", lambda _path: cfg)

    result = structural_check.run_structural_check(
        config_path=CONFIG_PATH,
        summary_path=None,
        mesh_path=None,
        step_path=None,
        hifi_dir=output_dir / "hifi",
        generate_paraview=False,
    )

    assert result.overall_status == "SKIP"
    assert result.static.status == "SKIP"
    assert "No mesh available" in result.static.message
