from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from hpa_mdo.aero.aero_sweep import load_su2_alpha_sweep


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")
    return path


def _fake_cfg(tmp_path: Path, origin_vsp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        project_name="Black Cat 004",
        flight=SimpleNamespace(
            velocity=6.5,
            air_density=1.225,
            kinematic_viscosity=1.46e-5,
        ),
        wing=SimpleNamespace(
            span=33.0,
            root_chord=1.30,
            tip_chord=0.435,
        ),
        io=SimpleNamespace(
            vsp_model=origin_vsp_path,
            output_dir=tmp_path / "output",
        ),
    )


def _sample_su2_mesh_text(*, wall_marker: str = "aircraft", farfield_marker: str = "farfield") -> str:
    return f"""
    NDIME= 3
    NPOIN= 4
    0.0 0.0 0.0
    1.0 0.0 0.0
    0.0 1.0 0.0
    0.0 0.0 1.0
    NELEM= 1
    10 0 1 2 3
    NMARK= 2
    MARKER_TAG= {wall_marker}
    MARKER_ELEMS= 1
    5 0 1 2
    MARKER_TAG= {farfield_marker}
    MARKER_ELEMS= 3
    5 0 1 3
    5 0 2 3
    5 1 2 3
    """


def test_prepare_origin_su2_alpha_sweep_writes_cases_and_configs(monkeypatch, tmp_path: Path) -> None:
    from hpa_mdo.aero.origin_su2 import prepare_origin_su2_alpha_sweep

    origin_vsp_path = _write_text(tmp_path / "origin.vsp3", "stub")
    cfg = _fake_cfg(tmp_path, origin_vsp_path)

    monkeypatch.setattr("hpa_mdo.aero.origin_su2.load_config", lambda _: cfg)
    monkeypatch.setattr(
        "hpa_mdo.aero.origin_su2._resolve_origin_reference_values",
        lambda _: {
            "sref": 35.175,
            "bref": 33.0,
            "cref": 1.13,
            "xcg": 0.25,
            "ycg": 0.0,
            "zcg": 0.0,
        },
    )

    def _fake_export(*, vsp3_path: str | Path, output_dir: str | Path) -> dict[str, str]:
        out_dir = Path(output_dir)
        return {
            "stl": str(_write_text(out_dir / "origin_surface.stl", "solid wing\nendsolid wing")),
            "step": str(_write_text(out_dir / "origin_surface.step", "ISO-10303-21;")),
        }

    monkeypatch.setattr("hpa_mdo.aero.origin_su2._export_origin_cfd_geometry", _fake_export)

    result = prepare_origin_su2_alpha_sweep(
        config_path=tmp_path / "blackcat.yaml",
        output_dir=tmp_path / "su2_alpha_sweep",
        aoa_list=[-2.0, 0.0],
    )

    assert result["case_count"] == 2
    assert Path(result["geometry"]["stl"]).exists()
    assert Path(result["geometry"]["step"]).exists()

    alpha_case = tmp_path / "su2_alpha_sweep" / "alpha_m2p0"
    runtime_cfg = (alpha_case / "su2_runtime.cfg").read_text(encoding="utf-8")
    metadata = json.loads((alpha_case / "case_metadata.json").read_text(encoding="utf-8"))

    assert "SOLVER= INC_NAVIER_STOKES" in runtime_cfg
    assert "REF_AREA= 35.175000" in runtime_cfg
    assert "REF_LENGTH= 1.130000" in runtime_cfg
    assert "REF_ORIGIN_MOMENT_X= 0.250000" in runtime_cfg
    assert "REF_ORIGIN_MOMENT_Y= 0.000000" in runtime_cfg
    assert "REF_ORIGIN_MOMENT_Z= 0.000000" in runtime_cfg
    assert "REF_ORIGIN_MOMENT=" not in runtime_cfg
    assert "AOA= -2.000000" in runtime_cfg
    assert "MARKER_HEATFLUX= ( aircraft, 0.0 )" in runtime_cfg
    assert "MARKER_FAR= ( farfield )" in runtime_cfg
    assert "MU_CONSTANT= 1.788500e-05" in runtime_cfg
    assert metadata["alpha_deg"] == -2.0
    assert (alpha_case / "PUT_MESH_HERE.md").exists()


def test_prepare_origin_su2_alpha_sweep_can_feed_the_shared_reader(monkeypatch, tmp_path: Path) -> None:
    from hpa_mdo.aero.origin_su2 import prepare_origin_su2_alpha_sweep

    origin_vsp_path = _write_text(tmp_path / "origin.vsp3", "stub")
    mesh_path = _write_text(tmp_path / "origin_mesh.su2", _sample_su2_mesh_text())
    cfg = _fake_cfg(tmp_path, origin_vsp_path)

    monkeypatch.setattr("hpa_mdo.aero.origin_su2.load_config", lambda _: cfg)
    monkeypatch.setattr(
        "hpa_mdo.aero.origin_su2._resolve_origin_reference_values",
        lambda _: {
            "sref": 35.175,
            "bref": 33.0,
            "cref": 1.13,
            "xcg": 0.25,
            "ycg": 0.0,
            "zcg": 0.0,
        },
    )
    monkeypatch.setattr(
        "hpa_mdo.aero.origin_su2._export_origin_cfd_geometry",
        lambda *, vsp3_path, output_dir: {
            "stl": str(_write_text(Path(output_dir) / "origin_surface.stl", "solid wing\nendsolid wing")),
            "step": str(_write_text(Path(output_dir) / "origin_surface.step", "ISO-10303-21;")),
        },
    )

    result = prepare_origin_su2_alpha_sweep(
        config_path=tmp_path / "blackcat.yaml",
        output_dir=tmp_path / "su2_alpha_sweep",
        aoa_list=[-2.0, 0.0],
        mesh_path=mesh_path,
    )

    alpha_zero = Path(result["cases"][1]["case_dir"])
    _write_text(
        alpha_zero / "history.csv",
        """
        "ITER","CD","CL","CMy"
        99,0.0360,1.0300,-0.0240
        """,
    )

    points = load_su2_alpha_sweep(tmp_path / "su2_alpha_sweep")
    assert len(points) == 1
    assert points[0].alpha_deg == 0.0
    assert points[0].cl == 1.03
    assert points[0].drag_n is not None
    assert (alpha_zero / "origin_mesh.su2").exists()


def test_prepare_origin_su2_alpha_sweep_can_auto_mesh_exported_stl(monkeypatch, tmp_path: Path) -> None:
    from hpa_mdo.aero.origin_su2 import prepare_origin_su2_alpha_sweep

    origin_vsp_path = _write_text(tmp_path / "origin.vsp3", "stub")
    cfg = _fake_cfg(tmp_path, origin_vsp_path)

    monkeypatch.setattr("hpa_mdo.aero.origin_su2.load_config", lambda _: cfg)
    monkeypatch.setattr(
        "hpa_mdo.aero.origin_su2._resolve_origin_reference_values",
        lambda _: {
            "sref": 35.175,
            "bref": 33.0,
            "cref": 1.13,
            "xcg": 0.25,
            "ycg": 0.0,
            "zcg": 0.0,
        },
    )
    monkeypatch.setattr(
        "hpa_mdo.aero.origin_su2._export_origin_cfd_geometry",
        lambda *, vsp3_path, output_dir: {
            "stl": str(_write_text(Path(output_dir) / "origin_surface.stl", "solid wing\nendsolid wing")),
            "step": str(_write_text(Path(output_dir) / "origin_surface.step", "ISO-10303-21;")),
        },
    )

    def _fake_generate_mesh(*args, **kwargs) -> dict[str, object]:
        output_path = Path(args[1])
        _write_text(output_path, _sample_su2_mesh_text())
        return {
            "MeshMode": "stl_external_box",
            "MeshFile": str(output_path),
            "PresetName": kwargs.get("preset_name", "baseline"),
            "MarkerElements": {"aircraft": 1, "farfield": 3},
            "Nodes": 4,
            "VolumeElements": 1,
        }

    monkeypatch.setattr(
        "hpa_mdo.aero.origin_su2.generate_stl_external_flow_mesh",
        _fake_generate_mesh,
    )

    result = prepare_origin_su2_alpha_sweep(
        config_path=tmp_path / "blackcat.yaml",
        output_dir=tmp_path / "su2_alpha_sweep",
        aoa_list=[0.0],
        auto_mesh=True,
        mesh_preset="study_medium",
    )

    assert result["mesh_preset"] == "study_medium"
    assert result["generated_mesh"]["MeshMode"] == "stl_external_box"
    assert result["generated_mesh"]["PresetName"] == "study_medium"
    assert Path(result["mesh_path"]).exists()
    assert Path(result["cases"][0]["mesh_path"]).exists()
    assert result["cases"][0]["mesh_validation"]["marker_names"] == ["aircraft", "farfield"]


def test_validate_su2_mesh_rejects_missing_required_marker(tmp_path: Path) -> None:
    from hpa_mdo.aero.origin_su2 import validate_su2_mesh

    mesh_path = _write_text(
        tmp_path / "origin_mesh.su2",
        _sample_su2_mesh_text(wall_marker="wing_surface", farfield_marker="farfield"),
    )

    try:
        validate_su2_mesh(mesh_path, required_markers=("aircraft", "farfield"))
    except ValueError as exc:
        assert "aircraft" in str(exc)
    else:  # pragma: no cover - red/green guard
        raise AssertionError("expected missing marker validation to fail")


def test_run_prepared_origin_su2_alpha_sweep_dry_run_writes_summary(monkeypatch, tmp_path: Path) -> None:
    from hpa_mdo.aero.origin_su2 import (
        prepare_origin_su2_alpha_sweep,
        run_prepared_origin_su2_alpha_sweep,
    )

    origin_vsp_path = _write_text(tmp_path / "origin.vsp3", "stub")
    mesh_path = _write_text(tmp_path / "origin_mesh.su2", _sample_su2_mesh_text())
    cfg = _fake_cfg(tmp_path, origin_vsp_path)

    monkeypatch.setattr("hpa_mdo.aero.origin_su2.load_config", lambda _: cfg)
    monkeypatch.setattr(
        "hpa_mdo.aero.origin_su2._resolve_origin_reference_values",
        lambda _: {
            "sref": 35.175,
            "bref": 33.0,
            "cref": 1.13,
            "xcg": 0.25,
            "ycg": 0.0,
            "zcg": 0.0,
        },
    )
    monkeypatch.setattr(
        "hpa_mdo.aero.origin_su2._export_origin_cfd_geometry",
        lambda *, vsp3_path, output_dir: {
            "stl": str(_write_text(Path(output_dir) / "origin_surface.stl", "solid wing\nendsolid wing")),
            "step": str(_write_text(Path(output_dir) / "origin_surface.step", "ISO-10303-21;")),
        },
    )

    prepared = prepare_origin_su2_alpha_sweep(
        config_path=tmp_path / "blackcat.yaml",
        output_dir=tmp_path / "su2_alpha_sweep",
        aoa_list=[-2.0, 0.0],
        mesh_path=mesh_path,
    )
    summary = run_prepared_origin_su2_alpha_sweep(
        prepared["sweep_dir"],
        dry_run=True,
        su2_binary="/tmp/fake/SU2_CFD",
    )

    assert summary["case_count"] == 2
    assert summary["cases"][0]["status"] == "dry_run"
    assert summary["cases"][0]["mesh_validation"]["marker_names"] == ["aircraft", "farfield"]
    assert Path(summary["summary_json"]).exists()


def test_run_prepared_origin_su2_alpha_sweep_executes_fake_solver(monkeypatch, tmp_path: Path) -> None:
    from hpa_mdo.aero.origin_su2 import (
        prepare_origin_su2_alpha_sweep,
        run_prepared_origin_su2_alpha_sweep,
    )

    origin_vsp_path = _write_text(tmp_path / "origin.vsp3", "stub")
    mesh_path = _write_text(tmp_path / "origin_mesh.su2", _sample_su2_mesh_text())
    fake_solver = _write_text(
        tmp_path / "fake_su2.sh",
        """
        #!/bin/sh
        printf '"ITER","CD","CL","CMy"\n20,0.0400,0.9900,-0.0200\n' > history.csv
        exit 0
        """,
    )
    fake_solver.chmod(0o755)
    cfg = _fake_cfg(tmp_path, origin_vsp_path)

    monkeypatch.setattr("hpa_mdo.aero.origin_su2.load_config", lambda _: cfg)
    monkeypatch.setattr(
        "hpa_mdo.aero.origin_su2._resolve_origin_reference_values",
        lambda _: {
            "sref": 35.175,
            "bref": 33.0,
            "cref": 1.13,
            "xcg": 0.25,
            "ycg": 0.0,
            "zcg": 0.0,
        },
    )
    monkeypatch.setattr(
        "hpa_mdo.aero.origin_su2._export_origin_cfd_geometry",
        lambda *, vsp3_path, output_dir: {
            "stl": str(_write_text(Path(output_dir) / "origin_surface.stl", "solid wing\nendsolid wing")),
            "step": str(_write_text(Path(output_dir) / "origin_surface.step", "ISO-10303-21;")),
        },
    )

    prepared = prepare_origin_su2_alpha_sweep(
        config_path=tmp_path / "blackcat.yaml",
        output_dir=tmp_path / "su2_alpha_sweep",
        aoa_list=[0.0],
        mesh_path=mesh_path,
    )
    summary = run_prepared_origin_su2_alpha_sweep(
        prepared["sweep_dir"],
        su2_binary=str(fake_solver),
    )

    assert summary["cases"][0]["status"] == "completed"
    assert Path(summary["cases"][0]["history_path"]).exists()
    points = load_su2_alpha_sweep(prepared["sweep_dir"])
    assert len(points) == 1
    assert points[0].cd == 0.04


def test_run_prepared_origin_su2_alpha_sweep_rejects_missing_history_after_execution(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from hpa_mdo.aero.origin_su2 import (
        prepare_origin_su2_alpha_sweep,
        run_prepared_origin_su2_alpha_sweep,
    )

    origin_vsp_path = _write_text(tmp_path / "origin.vsp3", "stub")
    mesh_path = _write_text(tmp_path / "origin_mesh.su2", _sample_su2_mesh_text())
    fake_solver = _write_text(
        tmp_path / "fake_su2_no_history.sh",
        """
        #!/bin/sh
        exit 0
        """,
    )
    fake_solver.chmod(0o755)
    cfg = _fake_cfg(tmp_path, origin_vsp_path)

    monkeypatch.setattr("hpa_mdo.aero.origin_su2.load_config", lambda _: cfg)
    monkeypatch.setattr(
        "hpa_mdo.aero.origin_su2._resolve_origin_reference_values",
        lambda _: {
            "sref": 35.175,
            "bref": 33.0,
            "cref": 1.13,
            "xcg": 0.25,
            "ycg": 0.0,
            "zcg": 0.0,
        },
    )
    monkeypatch.setattr(
        "hpa_mdo.aero.origin_su2._export_origin_cfd_geometry",
        lambda *, vsp3_path, output_dir: {
            "stl": str(_write_text(Path(output_dir) / "origin_surface.stl", "solid wing\nendsolid wing")),
            "step": str(_write_text(Path(output_dir) / "origin_surface.step", "ISO-10303-21;")),
        },
    )

    prepared = prepare_origin_su2_alpha_sweep(
        config_path=tmp_path / "blackcat.yaml",
        output_dir=tmp_path / "su2_alpha_sweep",
        aoa_list=[0.0],
        mesh_path=mesh_path,
    )

    try:
        run_prepared_origin_su2_alpha_sweep(
            prepared["sweep_dir"],
            su2_binary=str(fake_solver),
        )
    except RuntimeError as exc:
        assert "history" in str(exc).lower()
    else:  # pragma: no cover - red/green guard
        raise AssertionError("expected missing history to fail")
