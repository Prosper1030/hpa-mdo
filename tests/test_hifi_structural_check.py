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

MESH_WITH_WIRE_AND_MM_UNITS = """*NODE
1, 0.0, 0.0, 0.0
2, 0.0, 7500.0, 0.0
3, 0.0, 16500.0, 0.0
*NSET, NSET=ROOT
1
*NSET, NSET=WIRE_1
2
*NSET, NSET=TIP
3
*ELEMENT, TYPE=C3D4
10, 1, 2, 3, 1
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
    assert "Static tip-deflection check completed using" in report_text
    assert "Buckling check completed using" in report_text


def test_run_structural_check_matches_tip_by_frd_coordinates_when_ids_change(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    hifi_dir = output_dir / "hifi"
    hifi_dir.mkdir()
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
        lambda _path: np.asarray([[404.0, 0.0, 0.0, -2.5]]),
    )
    monkeypatch.setattr(
        structural_check,
        "parse_nodal_coordinates",
        lambda _path: np.asarray(
            [
                [401.0, 0.0, 0.0, 0.0],
                [404.0, 0.1, 1.0, 0.0],
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

    assert result.static.status == "PASS"
    assert result.static.actual == 2.5
    assert "FRD tip matched by coordinates" in result.static.message


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


def test_build_load_model_prefers_spar_csv_and_maps_mm_mesh(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    output_dir = tmp_path / "out"
    ansys_dir = output_dir / "ansys"
    ansys_dir.mkdir(parents=True)
    mesh = output_dir / "spar_model.inp"
    mesh.write_text(MESH_WITH_WIRE_AND_MM_UNITS, encoding="utf-8")
    csv_path = ansys_dir / "spar_data.csv"
    csv_path.write_text(
        "\n".join(
            [
                "Y_Position_m,Main_FZ_N,Rear_FZ_N",
                "0.0,0.0,0.0",
                "7.5,10.0,20.0",
                "16.5,-5.0,35.0",
            ]
        ),
        encoding="utf-8",
    )

    cfg.io.output_dir = str(output_dir)
    monkeypatch.setattr(structural_check, "load_config", lambda _path: cfg)

    scale = structural_check._mesh_length_scale_m_per_unit(mesh, cfg)
    load_model = structural_check._build_load_model(
        cfg=cfg,
        output_dir=output_dir,
        mesh_path=mesh,
        step_path=output_dir / "spar_model.step",
        explicit_tip_load_n=None,
        mesh_length_scale_m_per_unit=scale,
    )

    assert scale == 0.001
    assert "distributed nodal Fz from" in load_model.description
    assert load_model.total_fz_n == 60.0
    assert load_model.entries == ((2, 3, 30.0), (3, 3, 30.0))


def test_support_boundary_uses_wire_nset_when_present(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    mesh = tmp_path / "spar_model.inp"
    mesh.write_text(MESH_WITH_WIRE_AND_MM_UNITS, encoding="utf-8")

    boundaries = structural_check._support_boundary_from_mesh(mesh, cfg)

    assert boundaries == [(1, (1, 2, 3)), (2, (3,))]
