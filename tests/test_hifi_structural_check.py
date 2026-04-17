from __future__ import annotations

import json
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


def test_parse_optimization_summary_extracts_main_tip_from_production_report(
    tmp_path: Path,
) -> None:
    summary = tmp_path / "crossval_report.txt"
    summary.write_text(
        "\n".join(
            [
                "HPA-MDO Dual-Beam Production ANSYS Cross-Check Report",
                "  Export mode: dual_beam_production",
                "  Main tip deflection (uz, y=tip)    2393.720 mm",
            ]
        ),
        encoding="utf-8",
    )

    metrics = structural_check.parse_optimization_summary(summary)

    assert metrics["tip_deflection_m"] == 2.39372
    assert metrics["buckling_index"] is None


def test_parse_optimization_summary_extracts_tip_from_equivalent_crossval_report(
    tmp_path: Path,
) -> None:
    summary = tmp_path / "crossval_report.txt"
    summary.write_text(
        "\n".join(
            [
                "HPA-MDO ANSYS Cross-Validation Report",
                "  Export mode: equivalent_beam",
                "  Tip deflection (uz, y=16.5m)      2500.000 mm   2375.000 to 2625.000 mm",
            ]
        ),
        encoding="utf-8",
    )

    metrics = structural_check.parse_optimization_summary(summary)

    assert metrics["tip_deflection_m"] == 2.5
    assert metrics["buckling_index"] is None


def test_discover_default_summary_prefers_dual_beam_production_report(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    legacy_summary = output_dir / "optimization_summary.txt"
    legacy_summary.write_text("Tip deflection: 2500.0 mm (2.5 m)\n", encoding="utf-8")

    production_report = (
        tmp_path
        / "out_dual_beam_production_check"
        / "ansys"
        / "crossval_report.txt"
    )
    production_report.parent.mkdir(parents=True)
    production_report.write_text(
        "\n".join(
            [
                "HPA-MDO Dual-Beam Production ANSYS Cross-Check Report",
                "  Export mode: dual_beam_production",
                "  Main tip deflection (uz, y=tip)    2393.720 mm",
            ]
        ),
        encoding="utf-8",
    )

    resolved = structural_check._discover_default_summary(output_dir)

    assert resolved == production_report.resolve()


def test_discover_default_step_prefers_jig_shape_artifact(tmp_path: Path) -> None:
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    spar_model = output_dir / "spar_model.step"
    spar_jig = output_dir / "spar_jig_shape.step"
    spar_model.write_text("legacy", encoding="utf-8")
    spar_jig.write_text("jig", encoding="utf-8")

    resolved = structural_check._discover_default_step(output_dir)

    assert resolved == spar_jig.resolve()


def test_run_structural_check_uses_existing_mesh_and_writes_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg = _cfg(tmp_path)
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    ansys_dir = output_dir / "ansys"
    ansys_dir.mkdir()
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
    (ansys_dir / "spar_data.csv").write_text(
        "\n".join(
            [
                "Y_Position_m,Main_FZ_N,Rear_FZ_N",
                "0.0,0.0,0.0",
                "4.5,-10.0,-20.0",
                "16.5,-15.0,-25.0",
            ]
        ),
        encoding="utf-8",
    )

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
    summary_payload = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    assert result.overall_status == "PASS"
    assert result.static.status == "PASS"
    assert result.buckle.status == "PASS"
    assert result.paraview_script_path is not None
    assert result.paraview_script_path.exists()
    assert result.summary_json_path.exists()
    assert "Overall status: PASS" in report_text
    assert "Overall comparability: COMPARABLE" in report_text
    assert "Static tip-deflection check completed using" in report_text
    assert "Buckling check completed using" in report_text
    assert summary_payload["overall_status"] == "PASS"
    assert summary_payload["overall_comparability"] == "COMPARABLE"
    assert summary_payload["load_model"]["source_kind"] == "spar_csv"
    assert summary_payload["static"]["comparability"] == "COMPARABLE"


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


def test_run_structural_check_classifies_mesh_quality_solver_failures(
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
        log = inp_path.with_suffix(".log")
        log.write_text(
            "*INFO in gen3dnor: in node 1324 opposite normals are defined\n"
            "*ERROR in e_c3d: nonpositive jacobian\n",
            encoding="utf-8",
        )
        return {
            "frd": inp_path.with_suffix(".frd"),
            "dat": inp_path.with_suffix(".dat"),
            "log": log,
            "returncode": 1,
            "stdout": log.read_text(encoding="utf-8"),
            "stderr": "",
            "error": "ccx failed",
        }

    monkeypatch.setattr(structural_check, "run_static", fake_run_static)

    result = structural_check.run_structural_check(
        config_path=CONFIG_PATH,
        summary_path=summary,
        mesh_path=mesh,
        hifi_dir=hifi_dir,
        generate_paraview=False,
    )

    report_text = result.report_path.read_text(encoding="utf-8")
    summary_payload = json.loads(result.summary_json_path.read_text(encoding="utf-8"))

    assert result.overall_status == "WARN"
    assert result.static.issue_category == "mesh_quality"
    assert result.static.comparability == "NOT_COMPARABLE"
    assert result.static.diagnostics == ("opposite_normals x1", "nonpositive_jacobian x1")
    assert result.static.log_path == (hifi_dir / "wing_cruise_static.log").resolve()
    assert "Overall comparability: NOT_COMPARABLE" in report_text
    assert "Issue category: mesh_quality" in report_text
    assert summary_payload["overall_comparability"] == "NOT_COMPARABLE"
    assert summary_payload["static"]["issue_category"] == "mesh_quality"


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


def test_build_load_model_prefers_dual_beam_production_csv(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    output_dir = tmp_path / "out"
    legacy_dir = output_dir / "ansys"
    production_dir = tmp_path / "out_dual_beam_production_check" / "ansys"
    legacy_dir.mkdir(parents=True)
    production_dir.mkdir(parents=True)

    mesh = output_dir / "spar_model.inp"
    mesh.write_text(MESH_WITH_WIRE_AND_MM_UNITS, encoding="utf-8")
    (legacy_dir / "spar_data.csv").write_text(
        "\n".join(
            [
                "Y_Position_m,Main_FZ_N,Rear_FZ_N",
                "0.0,0.0,0.0",
                "7.5,5.0,5.0",
                "16.5,5.0,5.0",
            ]
        ),
        encoding="utf-8",
    )
    production_csv = production_dir / "spar_data.csv"
    production_csv.write_text(
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
        step_path=output_dir / "spar_jig_shape.step",
        explicit_tip_load_n=None,
        mesh_length_scale_m_per_unit=scale,
    )

    assert load_model.source_path == production_csv.resolve()
    assert load_model.total_fz_n == 60.0


def test_support_boundary_uses_wire_nset_when_present(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    mesh = tmp_path / "spar_model.inp"
    mesh.write_text(MESH_WITH_WIRE_AND_MM_UNITS, encoding="utf-8")

    boundaries = structural_check._support_boundary_from_mesh(mesh, cfg)

    assert boundaries == [(1, (1, 2, 3)), (2, (3,))]
