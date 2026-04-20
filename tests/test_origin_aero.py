from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hpa_mdo.aero.aero_sweep import AeroSweepPoint
from hpa_mdo.aero.origin_aero import run_origin_aero_sweep, write_origin_aero_artifacts


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


def _sample_vspaero_points() -> list[AeroSweepPoint]:
    return [
        AeroSweepPoint(
            solver="vspaero",
            alpha_deg=-2.0,
            cl=0.85,
            cd=0.026,
            cm=0.004,
            lift_n=2295.0,
            drag_n=70.0,
            source_path="/tmp/origin.polar",
        ),
        AeroSweepPoint(
            solver="vspaero",
            alpha_deg=0.0,
            cl=1.06,
            cd=0.033,
            cm=0.005,
            lift_n=2860.0,
            drag_n=89.0,
            source_path="/tmp/origin.polar",
        ),
    ]


def _sample_su2_points() -> list[AeroSweepPoint]:
    return [
        AeroSweepPoint(
            solver="su2",
            alpha_deg=-2.0,
            cl=0.82,
            cd=0.029,
            cm=-0.020,
            lift_n=2214.0,
            drag_n=78.0,
            source_path="/tmp/alpha_m2p0/history.csv",
        ),
        AeroSweepPoint(
            solver="su2",
            alpha_deg=0.0,
            cl=1.03,
            cd=0.036,
            cm=-0.024,
            lift_n=2779.0,
            drag_n=97.0,
            source_path="/tmp/alpha_0p0/history.csv",
        ),
    ]


def _stub_origin_geometry_contract(origin_vsp_path: Path) -> dict[str, object]:
    return {
        "contract_version": 1,
        "origin_vsp_path": str(origin_vsp_path.resolve()),
        "tail_geometry_confirmed": True,
        "control_surface_contract_confirmed": False,
        "surfaces": {
            "main_wing": {
                "kind": "main_wing",
                "name": "Main Wing",
                "detected": True,
                "span_m": 0.0,
                "root_chord_m": 0.0,
                "tip_chord_m": 0.0,
                "location": {"x": None, "y": None, "z": None},
                "rotation_deg": {"x": None, "y": None, "z": None},
                "symmetry_xz": True,
                "station_count": 0,
                "control_count": 0,
                "control_names": [],
            },
            "horizontal_tail": {
                "kind": "horizontal_tail",
                "name": "Elevator",
                "detected": True,
                "span_m": 0.0,
                "root_chord_m": 0.0,
                "tip_chord_m": 0.0,
                "location": {"x": None, "y": None, "z": None},
                "rotation_deg": {"x": None, "y": None, "z": None},
                "symmetry_xz": True,
                "station_count": 0,
                "control_count": 0,
                "control_names": [],
            },
            "vertical_fin": {
                "kind": "vertical_fin",
                "name": "Fin",
                "detected": True,
                "span_m": 0.0,
                "root_chord_m": 0.0,
                "tip_chord_m": 0.0,
                "location": {"x": None, "y": None, "z": None},
                "rotation_deg": {"x": None, "y": None, "z": None},
                "symmetry_xz": False,
                "station_count": 0,
                "control_count": 0,
                "control_names": [],
            },
        },
    }


def test_write_origin_aero_artifacts_writes_solver_outputs_and_bundle(tmp_path: Path) -> None:
    bundle = write_origin_aero_artifacts(
        output_dir=tmp_path,
        vspaero_points=_sample_vspaero_points(),
        su2_points=_sample_su2_points(),
        metadata={
            "config_path": str(tmp_path / "blackcat.yaml"),
            "origin_vsp_path": str(tmp_path / "origin.vsp3"),
        },
    )

    expected = {
        "analysis_bundle.json",
        "vspaero_results.csv",
        "vspaero_results.json",
        "vspaero_results.md",
        "vspaero_plots.png",
        "su2_results.csv",
        "su2_results.json",
        "su2_results.md",
        "comparison_plots.png",
    }
    assert expected.issubset({path.name for path in tmp_path.iterdir()})

    payload = json.loads((tmp_path / "analysis_bundle.json").read_text(encoding="utf-8"))
    assert payload["vspaero"]["count"] == 2
    assert payload["su2"]["count"] == 2
    assert Path(bundle["vspaero"]["files"]["csv"]).exists()
    assert Path(bundle["su2"]["files"]["markdown"]).exists()


def test_run_origin_aero_sweep_runs_builder_and_optionally_loads_su2(monkeypatch, tmp_path: Path) -> None:
    origin_vsp_path = tmp_path / "origin.vsp3"
    origin_vsp_path.write_text("stub\n", encoding="utf-8")
    lod_path = _write_text(
        tmp_path / "origin.lod",
        """
        Sref_ 35.1750000 Lunit^2
        Bref_ 33.0000000 Lunit
        Cref_ 1.0425000 Lunit
        Rho_ 1.2250000 Munit/Lunit^3
        Vinf_ 6.5000000 Lunit/Tunit
        """,
    )
    polar_path = _write_text(
        tmp_path / "origin.polar",
        """
        Beta Mach AoA Re/1e6 CLo CLi CLtot CDo CDi CDtot CSo CSi CStot L/D E CMox CMoy CMoz CMix CMiy CMiz CMxtot CMytot CMztot
        0.0 0.0 -2.0 0.46 -0.0002 0.8463 0.8461 0.0182 0.0084 0.0266 0.0 0.0 0.0 31.7 0.87 0.0 0.0040 0.0 0.0 -0.4033 0.0 0.0 -0.3992 0.0
        0.0 0.0  0.0 0.46 -0.0010 1.0577 1.0567 0.0206 0.0127 0.0333 0.0 0.0 0.0 31.7 0.90 0.0 0.0045 0.0 0.0 -0.4943 0.0 0.0 -0.4898 0.0
        """,
    )

    su2_dir = tmp_path / "su2_sweep"
    _write_text(
        su2_dir / "alpha_m2p0" / "history.csv",
        """
        "ITER","CD","CL","CMy"
        49,0.0290,0.8200,-0.0200
        """,
    )
    _write_text(
        su2_dir / "alpha_m2p0" / "su2_runtime.cfg",
        """
        REF_AREA= 35.175
        INC_DENSITY_INIT= 1.225
        INC_VELOCITY_INIT= ( 6.5, 0.0, 0.0 )
        """,
    )

    cfg = SimpleNamespace(
        project_name="Black Cat 004",
        io=SimpleNamespace(vsp_model=origin_vsp_path, output_dir=tmp_path / "output"),
    )

    captured: dict[str, object] = {}

    class FakeBuilder:
        def __init__(self, loaded_cfg):
            captured["cfg"] = loaded_cfg

        def run_vspaero(self, vsp3_path: str, aoa_list: list[float], output_dir: str) -> dict:
            captured["vsp3_path"] = vsp3_path
            captured["aoa_list"] = list(aoa_list)
            captured["output_dir"] = output_dir
            return {
                "success": True,
                "lod_path": str(lod_path),
                "polar_path": str(polar_path),
                "analysis_method": "panel",
                "solver_backend": "fake_vspaero",
                "error": None,
            }

    monkeypatch.setattr("hpa_mdo.aero.origin_aero.load_config", lambda _: cfg)
    monkeypatch.setattr("hpa_mdo.aero.origin_aero.VSPBuilder", FakeBuilder)
    monkeypatch.setattr(
        "hpa_mdo.aero.origin_aero.build_origin_geometry_contract",
        lambda *, config_path, cfg=None: _stub_origin_geometry_contract(origin_vsp_path),
    )

    bundle = run_origin_aero_sweep(
        config_path=tmp_path / "blackcat.yaml",
        output_dir=tmp_path / "analysis",
        aoa_list=[-2.0, 0.0],
        su2_sweep_dir=su2_dir,
    )

    assert captured["vsp3_path"] == str(origin_vsp_path)
    assert captured["aoa_list"] == [-2.0, 0.0]
    assert Path(bundle["bundle_json"]).exists()
    payload = json.loads(Path(bundle["bundle_json"]).read_text(encoding="utf-8"))
    assert payload["vspaero"]["count"] == 2
    assert payload["su2"]["count"] == 1


def test_run_origin_aero_sweep_can_prepare_su2_cases_before_analysis(
    monkeypatch,
    tmp_path: Path,
) -> None:
    origin_vsp_path = tmp_path / "origin.vsp3"
    origin_vsp_path.write_text("stub\n", encoding="utf-8")
    lod_path = _write_text(
        tmp_path / "origin.lod",
        """
        Sref_ 35.1750000 Lunit^2
        Bref_ 33.0000000 Lunit
        Cref_ 1.0425000 Lunit
        Rho_ 1.2250000 Munit/Lunit^3
        Vinf_ 6.5000000 Lunit/Tunit
        """,
    )
    polar_path = _write_text(
        tmp_path / "origin.polar",
        """
        Beta Mach AoA Re/1e6 CLo CLi CLtot CDo CDi CDtot CSo CSi CStot L/D E CMox CMoy CMoz CMix CMiy CMiz CMxtot CMytot CMztot
        0.0 0.0 -2.0 0.46 -0.0002 0.8463 0.8461 0.0182 0.0084 0.0266 0.0 0.0 0.0 31.7 0.87 0.0 0.0040 0.0 0.0 -0.4033 0.0 0.0 -0.3992 0.0
        0.0 0.0  0.0 0.46 -0.0010 1.0577 1.0567 0.0206 0.0127 0.0333 0.0 0.0 0.0 31.7 0.90 0.0 0.0045 0.0 0.0 -0.4943 0.0 0.0 -0.4898 0.0
        """,
    )

    cfg = SimpleNamespace(
        project_name="Black Cat 004",
        io=SimpleNamespace(vsp_model=origin_vsp_path, output_dir=tmp_path / "output"),
    )

    class FakeBuilder:
        def __init__(self, loaded_cfg):
            self.cfg = loaded_cfg

        def run_vspaero(self, vsp3_path: str, aoa_list: list[float], output_dir: str) -> dict:
            return {
                "success": True,
                "lod_path": str(lod_path),
                "polar_path": str(polar_path),
                "analysis_method": "panel",
                "solver_backend": "fake_vspaero",
                "error": None,
            }

    def _fake_prepare(**kwargs) -> dict[str, object]:
        sweep_dir = Path(kwargs["output_dir"])
        _write_text(
            sweep_dir / "alpha_0p0" / "history.csv",
            """
            "ITER","CD","CL","CMy"
            49,0.0360,1.0300,-0.0240
            """,
        )
        _write_text(
            sweep_dir / "alpha_0p0" / "su2_runtime.cfg",
            """
            AOA= 0.0
            REF_AREA= 35.175
            INC_DENSITY_INIT= 1.225
            INC_VELOCITY_INIT= ( 6.5, 0.0, 0.0 )
            """,
        )
        return {
            "sweep_dir": str(sweep_dir),
            "case_count": 2,
            "cases": [{"alpha_deg": -2.0}, {"alpha_deg": 0.0}],
        }

    monkeypatch.setattr("hpa_mdo.aero.origin_aero.load_config", lambda _: cfg)
    monkeypatch.setattr("hpa_mdo.aero.origin_aero.VSPBuilder", FakeBuilder)
    monkeypatch.setattr(
        "hpa_mdo.aero.origin_aero.build_origin_geometry_contract",
        lambda *, config_path, cfg=None: _stub_origin_geometry_contract(origin_vsp_path),
    )
    monkeypatch.setattr("hpa_mdo.aero.origin_aero.prepare_origin_su2_alpha_sweep", _fake_prepare)

    bundle = run_origin_aero_sweep(
        config_path=tmp_path / "blackcat.yaml",
        output_dir=tmp_path / "analysis",
        aoa_list=[-2.0, 0.0],
        prepare_su2=True,
    )

    payload = json.loads(Path(bundle["bundle_json"]).read_text(encoding="utf-8"))
    assert payload["metadata"]["origin_geometry_contract"]["tail_geometry_confirmed"] is True
    assert Path(payload["metadata"]["origin_geometry_contract_json"]).exists()
    assert payload["metadata"]["su2_preparation"]["case_count"] == 2
    assert payload["su2"]["count"] == 1


def test_run_origin_aero_sweep_can_dry_run_prepared_su2_cases(
    monkeypatch,
    tmp_path: Path,
) -> None:
    origin_vsp_path = tmp_path / "origin.vsp3"
    origin_vsp_path.write_text("stub\n", encoding="utf-8")
    lod_path = _write_text(
        tmp_path / "origin.lod",
        """
        Sref_ 35.1750000 Lunit^2
        Bref_ 33.0000000 Lunit
        Cref_ 1.0425000 Lunit
        Rho_ 1.2250000 Munit/Lunit^3
        Vinf_ 6.5000000 Lunit/Tunit
        """,
    )
    polar_path = _write_text(
        tmp_path / "origin.polar",
        """
        Beta Mach AoA Re/1e6 CLo CLi CLtot CDo CDi CDtot CSo CSi CStot L/D E CMox CMoy CMoz CMix CMiy CMiz CMxtot CMytot CMztot
        0.0 0.0 -2.0 0.46 -0.0002 0.8463 0.8461 0.0182 0.0084 0.0266 0.0 0.0 0.0 31.7 0.87 0.0 0.0040 0.0 0.0 -0.4033 0.0 0.0 -0.3992 0.0
        0.0 0.0  0.0 0.46 -0.0010 1.0577 1.0567 0.0206 0.0127 0.0333 0.0 0.0 0.0 31.7 0.90 0.0 0.0045 0.0 0.0 -0.4943 0.0 0.0 -0.4898 0.0
        """,
    )

    cfg = SimpleNamespace(
        project_name="Black Cat 004",
        io=SimpleNamespace(vsp_model=origin_vsp_path, output_dir=tmp_path / "output"),
    )

    class FakeBuilder:
        def __init__(self, loaded_cfg):
            self.cfg = loaded_cfg

        def run_vspaero(self, vsp3_path: str, aoa_list: list[float], output_dir: str) -> dict:
            return {
                "success": True,
                "lod_path": str(lod_path),
                "polar_path": str(polar_path),
                "analysis_method": "panel",
                "solver_backend": "fake_vspaero",
                "error": None,
            }

    def _fake_prepare(**kwargs) -> dict[str, object]:
        sweep_dir = Path(kwargs["output_dir"])
        _write_text(
            sweep_dir / "alpha_0p0" / "su2_runtime.cfg",
            """
            AOA= 0.0
            REF_AREA= 35.175
            INC_DENSITY_INIT= 1.225
            INC_VELOCITY_INIT= ( 6.5, 0.0, 0.0 )
            """,
        )
        return {
            "sweep_dir": str(sweep_dir),
            "case_count": 1,
            "cases": [{"alpha_deg": 0.0}],
        }

    def _fake_run_prepared(*args, **kwargs) -> dict[str, object]:
        return {
            "case_count": 1,
            "dry_run": True,
            "cases": [
                {
                    "case_name": "alpha_0p0",
                    "status": "completed_but_weak",
                    "mesh_preset": "study_medium",
                }
            ],
            "summary_json": str(tmp_path / "su2_run_summary.json"),
        }

    monkeypatch.setattr("hpa_mdo.aero.origin_aero.load_config", lambda _: cfg)
    monkeypatch.setattr("hpa_mdo.aero.origin_aero.VSPBuilder", FakeBuilder)
    monkeypatch.setattr(
        "hpa_mdo.aero.origin_aero.build_origin_geometry_contract",
        lambda *, config_path, cfg=None: _stub_origin_geometry_contract(origin_vsp_path),
    )
    monkeypatch.setattr("hpa_mdo.aero.origin_aero.prepare_origin_su2_alpha_sweep", _fake_prepare)
    monkeypatch.setattr(
        "hpa_mdo.aero.origin_aero.run_prepared_origin_su2_alpha_sweep",
        _fake_run_prepared,
    )

    bundle = run_origin_aero_sweep(
        config_path=tmp_path / "blackcat.yaml",
        output_dir=tmp_path / "analysis",
        aoa_list=[-2.0, 0.0],
        prepare_su2=True,
        dry_run_su2_cases=True,
    )

    payload = json.loads(Path(bundle["bundle_json"]).read_text(encoding="utf-8"))
    assert payload["metadata"]["su2_run_summary"]["dry_run"] is True
    assert payload["metadata"]["su2_run_summary"]["cases"][0]["mesh_preset"] == "study_medium"
    assert payload["metadata"]["su2_run_summary"]["cases"][0]["status"] in {
        "completed_converged",
        "completed_but_weak",
    }
    assert payload["metadata"]["su2_analysis_note"] is not None


def test_run_origin_aero_sweep_passes_auto_mesh_flag_into_prepare(
    monkeypatch,
    tmp_path: Path,
) -> None:
    origin_vsp_path = tmp_path / "origin.vsp3"
    origin_vsp_path.write_text("stub\n", encoding="utf-8")
    lod_path = _write_text(
        tmp_path / "origin.lod",
        """
        Sref_ 35.1750000 Lunit^2
        Bref_ 33.0000000 Lunit
        Cref_ 1.0425000 Lunit
        Rho_ 1.2250000 Munit/Lunit^3
        Vinf_ 6.5000000 Lunit/Tunit
        """,
    )
    polar_path = _write_text(
        tmp_path / "origin.polar",
        """
        Beta Mach AoA Re/1e6 CLo CLi CLtot CDo CDi CDtot CSo CSi CStot L/D E CMox CMoy CMoz CMix CMiy CMiz CMxtot CMytot CMztot
        0.0 0.0 0.0 0.46 -0.0010 1.0577 1.0567 0.0206 0.0127 0.0333 0.0 0.0 0.0 31.7 0.90 0.0 0.0045 0.0 0.0 -0.4943 0.0 0.0 -0.4898 0.0
        """,
    )

    cfg = SimpleNamespace(
        project_name="Black Cat 004",
        io=SimpleNamespace(vsp_model=origin_vsp_path, output_dir=tmp_path / "output"),
    )

    class FakeBuilder:
        def __init__(self, loaded_cfg):
            self.cfg = loaded_cfg

        def run_vspaero(self, vsp3_path: str, aoa_list: list[float], output_dir: str) -> dict:
            return {
                "success": True,
                "lod_path": str(lod_path),
                "polar_path": str(polar_path),
                "analysis_method": "panel",
                "solver_backend": "fake_vspaero",
                "error": None,
            }

    def _fake_prepare(**kwargs) -> dict[str, object]:
        assert kwargs["auto_mesh"] is True
        sweep_dir = Path(kwargs["output_dir"])
        sweep_dir.mkdir(parents=True, exist_ok=True)
        return {
            "sweep_dir": str(sweep_dir),
            "case_count": 1,
            "cases": [{"alpha_deg": 0.0}],
            "mesh_path": str(tmp_path / "origin_mesh.su2"),
        }

    monkeypatch.setattr("hpa_mdo.aero.origin_aero.load_config", lambda _: cfg)
    monkeypatch.setattr("hpa_mdo.aero.origin_aero.VSPBuilder", FakeBuilder)
    monkeypatch.setattr(
        "hpa_mdo.aero.origin_aero.build_origin_geometry_contract",
        lambda *, config_path, cfg=None: _stub_origin_geometry_contract(origin_vsp_path),
    )
    monkeypatch.setattr("hpa_mdo.aero.origin_aero.prepare_origin_su2_alpha_sweep", _fake_prepare)

    bundle = run_origin_aero_sweep(
        config_path=tmp_path / "blackcat.yaml",
        output_dir=tmp_path / "analysis",
        aoa_list=[0.0],
        prepare_su2=True,
        auto_mesh_su2=True,
    )

    payload = json.loads(Path(bundle["bundle_json"]).read_text(encoding="utf-8"))
    assert payload["metadata"]["su2_preparation"]["case_count"] == 1


def test_run_origin_aero_sweep_writes_mesh_study_artifacts_and_bundle_metadata(
    monkeypatch,
    tmp_path: Path,
) -> None:
    origin_vsp_path = tmp_path / "origin.vsp3"
    origin_vsp_path.write_text("stub\n", encoding="utf-8")
    lod_path = _write_text(
        tmp_path / "origin.lod",
        """
        Sref_ 35.1750000 Lunit^2
        Bref_ 33.0000000 Lunit
        Cref_ 1.0425000 Lunit
        Rho_ 1.2250000 Munit/Lunit^3
        Vinf_ 6.5000000 Lunit/Tunit
        """,
    )
    polar_path = _write_text(
        tmp_path / "origin.polar",
        """
        Beta Mach AoA Re/1e6 CLo CLi CLtot CDo CDi CDtot CSo CSi CStot L/D E CMox CMoy CMoz CMix CMiy CMiz CMxtot CMytot CMztot
        0.0 0.0 0.0 0.46 -0.0010 1.0577 1.0567 0.0206 0.0127 0.0333 0.0 0.0 0.0 31.7 0.90 0.0 0.0045 0.0 0.0 -0.4943 0.0 0.0 -0.4898 0.0
        """,
    )

    cfg = SimpleNamespace(
        project_name="Black Cat 004",
        io=SimpleNamespace(vsp_model=origin_vsp_path, output_dir=tmp_path / "output"),
    )

    class FakeBuilder:
        def __init__(self, loaded_cfg):
            self.cfg = loaded_cfg

        def run_vspaero(self, vsp3_path: str, aoa_list: list[float], output_dir: str) -> dict:
            return {
                "success": True,
                "lod_path": str(lod_path),
                "polar_path": str(polar_path),
                "analysis_method": "panel",
                "solver_backend": "fake_vspaero",
                "error": None,
            }

    cd_by_preset = {
        "study_coarse": 0.0310,
        "study_medium": 0.0317,
        "study_fine": 0.0324,
    }

    def _fake_prepare(**kwargs) -> dict[str, object]:
        sweep_dir = Path(kwargs["output_dir"])
        sweep_dir.mkdir(parents=True, exist_ok=True)
        preset = kwargs["mesh_preset"]
        _write_text(
            sweep_dir / "alpha_0p0" / "su2_runtime.cfg",
            """
            AOA= 0.0
            REF_AREA= 35.175
            INC_DENSITY_INIT= 1.225
            INC_VELOCITY_INIT= ( 6.5, 0.0, 0.0 )
            """,
        )
        return {
            "sweep_dir": str(sweep_dir),
            "case_count": 1,
            "cases": [{"alpha_deg": 0.0}],
            "mesh_preset": preset,
        }

    def _fake_run_prepared(sweep_dir: str | Path, *args, **kwargs) -> dict[str, object]:
        sweep_path = Path(sweep_dir)
        preset = sweep_path.name
        _write_text(
            sweep_path / "alpha_0p0" / "history.csv",
            f"""
            "ITER","CD","CL","CMy"
            49,{cd_by_preset[preset]:.4f},1.0100,-0.0200
            """,
        )
        return {
            "case_count": 1,
            "dry_run": False,
            "cases": [{"case_name": "alpha_0p0", "status": "completed_converged", "mesh_preset": preset}],
        }

    monkeypatch.setattr("hpa_mdo.aero.origin_aero.load_config", lambda _: cfg)
    monkeypatch.setattr("hpa_mdo.aero.origin_aero.VSPBuilder", FakeBuilder)
    monkeypatch.setattr(
        "hpa_mdo.aero.origin_aero.build_origin_geometry_contract",
        lambda *, config_path, cfg=None: _stub_origin_geometry_contract(origin_vsp_path),
    )
    monkeypatch.setattr("hpa_mdo.aero.origin_aero.prepare_origin_su2_alpha_sweep", _fake_prepare)
    monkeypatch.setattr("hpa_mdo.aero.origin_aero.run_prepared_origin_su2_alpha_sweep", _fake_run_prepared)

    bundle = run_origin_aero_sweep(
        config_path=tmp_path / "blackcat.yaml",
        output_dir=tmp_path / "analysis",
        aoa_list=[0.0],
        auto_mesh_su2=True,
        run_su2_cases=True,
        mesh_study_presets=["study_coarse", "study_medium", "study_fine"],
    )

    payload = json.loads(Path(bundle["bundle_json"]).read_text(encoding="utf-8"))
    mesh_study = payload["metadata"]["mesh_study_verdict"]
    assert mesh_study["verdict"] == "usable_for_comparison"
    assert mesh_study["preset_count"] == 3
    assert Path(payload["metadata"]["mesh_study_summary_json"]).exists()
    assert Path(payload["metadata"]["mesh_study_report_md"]).exists()


def test_run_origin_aero_sweep_rejects_mesh_study_without_real_run_stage(
    monkeypatch,
    tmp_path: Path,
) -> None:
    origin_vsp_path = tmp_path / "origin.vsp3"
    origin_vsp_path.write_text("stub\n", encoding="utf-8")
    lod_path = _write_text(
        tmp_path / "origin.lod",
        """
        Sref_ 35.1750000 Lunit^2
        Bref_ 33.0000000 Lunit
        Cref_ 1.0425000 Lunit
        Rho_ 1.2250000 Munit/Lunit^3
        Vinf_ 6.5000000 Lunit/Tunit
        """,
    )
    polar_path = _write_text(
        tmp_path / "origin.polar",
        """
        Beta Mach AoA Re/1e6 CLo CLi CLtot CDo CDi CDtot CSo CSi CStot L/D E CMox CMoy CMoz CMix CMiy CMiz CMxtot CMytot CMztot
        0.0 0.0 0.0 0.46 -0.0010 1.0577 1.0567 0.0206 0.0127 0.0333 0.0 0.0 0.0 31.7 0.90 0.0 0.0045 0.0 0.0 -0.4943 0.0 0.0 -0.4898 0.0
        """,
    )

    cfg = SimpleNamespace(
        project_name="Black Cat 004",
        io=SimpleNamespace(vsp_model=origin_vsp_path, output_dir=tmp_path / "output"),
    )

    class FakeBuilder:
        def __init__(self, loaded_cfg):
            self.cfg = loaded_cfg

        def run_vspaero(self, vsp3_path: str, aoa_list: list[float], output_dir: str) -> dict:
            return {
                "success": True,
                "lod_path": str(lod_path),
                "polar_path": str(polar_path),
                "analysis_method": "panel",
                "solver_backend": "fake_vspaero",
                "error": None,
            }

    def _fake_prepare(**kwargs) -> dict[str, object]:
        sweep_dir = Path(kwargs["output_dir"])
        _write_text(
            sweep_dir / "alpha_0p0" / "su2_runtime.cfg",
            """
            AOA= 0.0
            REF_AREA= 35.175
            INC_DENSITY_INIT= 1.225
            INC_VELOCITY_INIT= ( 6.5, 0.0, 0.0 )
            """,
        )
        return {
            "sweep_dir": str(sweep_dir),
            "case_count": 1,
            "cases": [{"alpha_deg": 0.0}],
            "mesh_preset": kwargs["mesh_preset"],
        }

    monkeypatch.setattr("hpa_mdo.aero.origin_aero.load_config", lambda _: cfg)
    monkeypatch.setattr("hpa_mdo.aero.origin_aero.VSPBuilder", FakeBuilder)
    monkeypatch.setattr(
        "hpa_mdo.aero.origin_aero.build_origin_geometry_contract",
        lambda *, config_path, cfg=None: _stub_origin_geometry_contract(origin_vsp_path),
    )
    monkeypatch.setattr("hpa_mdo.aero.origin_aero.prepare_origin_su2_alpha_sweep", _fake_prepare)

    with pytest.raises(ValueError, match="mesh-study verdict generation requires run_su2_cases=True"):
        run_origin_aero_sweep(
            config_path=tmp_path / "blackcat.yaml",
            output_dir=tmp_path / "analysis",
            aoa_list=[0.0],
            auto_mesh_su2=True,
            mesh_study_presets=["study_coarse", "study_medium", "study_fine"],
        )
