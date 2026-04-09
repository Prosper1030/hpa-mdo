from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
import yaml
from pydantic import ValidationError

from hpa_mdo.core.aircraft import Aircraft, AirfoilData
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


def test_blackcat_airfoil_tc_loaded_from_config():
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"

    cfg = load_config(config_path)

    assert cfg.wing.airfoil_root_tc == pytest.approx(0.117)
    assert cfg.wing.airfoil_tip_tc == pytest.approx(0.140)


def test_blackcat_lift_wire_angle_loaded_from_config():
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"

    cfg = load_config(config_path)

    assert cfg.lift_wires.wire_angle_deg == pytest.approx(11.3)


def test_aircraft_converts_airfoil_camber_fraction_to_meters():
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"
    cfg = load_config(config_path)

    fake_airfoil = AirfoilData(
        name="unit-test",
        x=np.array([0.0, 1.0]),
        z_upper=np.array([0.10, 0.10]),
        z_lower=np.array([0.00, 0.00]),
    )

    with patch("hpa_mdo.core.aircraft._try_load_airfoil", side_effect=[fake_airfoil, fake_airfoil]):
        with patch.object(cfg.solver, "n_beam_nodes", 5):
            aircraft = Aircraft.from_config(cfg)

    expected_camber = 0.05 * aircraft.wing.chord
    np.testing.assert_allclose(aircraft.wing.main_spar_z_camber, expected_camber)
    np.testing.assert_allclose(aircraft.wing.rear_spar_z_camber, expected_camber)


def test_load_config_rejects_segment_sum_mismatch(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["main_spar"]["segments"] = [1.0, 3.0, 3.0, 3.0, 3.0, 3.0]  # sum = 16.0

    bad_cfg = tmp_path / "bad_segments.yaml"
    bad_cfg.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_config(bad_cfg)


def test_load_config_rejects_lift_wire_not_on_joint(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["lift_wires"]["attachments"][0]["y"] = 7.4

    bad_cfg = tmp_path / "bad_lift_wire.yaml"
    bad_cfg.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_config(bad_cfg)
