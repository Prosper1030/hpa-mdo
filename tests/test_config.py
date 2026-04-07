from __future__ import annotations

from pathlib import Path

from hpa_mdo.core.config import load_config


def test_load_config_applies_local_sync_root_overlay(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"
    sync_root = tmp_path / "SyncFile"
    overlay_path = tmp_path / "local_paths.yaml"
    overlay_path.write_text(
        "io:\n"
        f"  sync_root: \"{sync_root.as_posix()}\"\n",
        encoding="utf-8",
    )

    cfg = load_config(config_path, local_paths_path=overlay_path)

    assert cfg.io.sync_root == sync_root.resolve()
    assert cfg.io.vsp_lod == (
        sync_root / "Aerodynamics/black cat 004 wing only/blackcat 004 wing only_VSPGeom.lod"
    ).resolve()
    assert cfg.io.vsp_polar == (
        sync_root / "Aerodynamics/black cat 004 wing only/blackcat 004 wing only_VSPGeom.polar"
    ).resolve()
    assert cfg.io.airfoil_dir == (sync_root / "Aerodynamics/airfoil").resolve()
    assert cfg.io.output_dir == (repo_root / "output/blackcat_004").resolve()
    assert cfg.io.training_db == (repo_root / "database/training_data.csv").resolve()


def test_load_config_honors_environment_override(tmp_path, monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"
    overlay_path = tmp_path / "local_paths.yaml"
    sync_root = tmp_path / "SharedSync"
    overlay_path.write_text(
        "io:\n"
        f"  sync_root: \"{sync_root.as_posix()}\"\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HPA_MDO_LOCAL_PATHS", str(overlay_path))

    cfg = load_config(config_path)

    assert cfg.io.sync_root == sync_root.resolve()
