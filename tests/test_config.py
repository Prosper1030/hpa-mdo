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
        f'io:\n  sync_root: "{sync_root.as_posix()}"\n',
        encoding="utf-8",
    )

    cfg = load_config(config_path, local_paths_path=overlay_path)

    assert cfg.io.sync_root == sync_root.resolve()
    assert (
        cfg.io.vsp_lod
        == (
            sync_root / "Aerodynamics/black cat 004 wing only/blackcat 004 wing only_VSPGeom.lod"
        ).resolve()
    )
    assert (
        cfg.io.vsp_polar
        == (
            sync_root / "Aerodynamics/black cat 004 wing only/blackcat 004 wing only_VSPGeom.polar"
        ).resolve()
    )
    assert cfg.io.airfoil_dir == (sync_root / "Aerodynamics/airfoil").resolve()
    assert cfg.io.output_dir == (repo_root / "output/blackcat_004").resolve()
    assert cfg.io.training_db == (repo_root / "database/training_data.csv").resolve()


def test_load_config_honors_environment_override(tmp_path, monkeypatch):
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"
    overlay_path = tmp_path / "local_paths.yaml"
    sync_root = tmp_path / "SharedSync"
    overlay_path.write_text(
        f'io:\n  sync_root: "{sync_root.as_posix()}"\n',
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


def test_multi_wire_layout_derives_per_attachment_angles(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["lift_wires"]["attachments"] = [
        {"y": 4.5, "fuselage_z": -1.5, "label": "wire-1"},
        {"y": 10.5, "fuselage_z": -1.5, "label": "wire-2"},
    ]

    cfg_path = tmp_path / "multi_wire.yaml"
    cfg_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    cfg = load_config(cfg_path)

    angles = cfg.lift_wires.attachment_wire_angles_deg()
    assert len(angles) == 2
    assert angles[0] == pytest.approx(np.degrees(np.arctan2(1.5, 4.5)))
    assert angles[1] == pytest.approx(np.degrees(np.arctan2(1.5, 10.5)))


def test_blackcat_loaded_shape_tolerances_loaded_from_solver_config():
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"

    cfg = load_config(config_path)

    assert cfg.solver.loaded_shape_z_tol_m == pytest.approx(0.025)
    assert cfg.solver.loaded_shape_twist_tol_deg == pytest.approx(0.15)


def test_blackcat_spar_layup_defaults_loaded_from_config():
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"

    cfg = load_config(config_path)

    assert cfg.main_spar.layup_mode == "isotropic"
    assert cfg.main_spar.ply_material == "cfrp_ply_hm"
    assert cfg.main_spar.min_plies_0 == 1
    assert cfg.main_spar.min_plies_45_pairs == 1
    assert cfg.main_spar.min_plies_90 == 0
    assert cfg.main_spar.max_total_plies == 14
    assert cfg.main_spar.max_ply_drop_per_segment == 2
    assert cfg.rear_spar.layup_mode == "isotropic"
    assert cfg.rear_spar.ply_material == "cfrp_ply_hm"
    assert cfg.rear_spar.max_ply_drop_per_segment == 2


def test_blackcat_beta_sweep_gates_loaded_from_config():
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"

    cfg = load_config(config_path)

    assert cfg.aero_gates.max_sideslip_deg == pytest.approx(12.0)
    assert cfg.aero_gates.min_spiral_time_to_double_s == pytest.approx(10.0)
    assert cfg.aero_gates.beta_sweep_values == pytest.approx([0.0, 5.0, 10.0, 12.0])


def test_blackcat_empennage_geometry_loaded_from_config():
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"

    cfg = load_config(config_path)

    assert cfg.horizontal_tail.name == "Elevator"
    assert cfg.horizontal_tail.span == pytest.approx(3.0)
    assert cfg.horizontal_tail.symmetry == "xz"
    assert cfg.horizontal_tail.control_surface_limit_deg == pytest.approx(20.0)

    assert cfg.vertical_fin.name == "Fin"
    assert cfg.vertical_fin.z_location == pytest.approx(-0.7)
    assert cfg.vertical_fin.x_rotation_deg == pytest.approx(90.0)
    assert cfg.vertical_fin.control_surface_limit_deg == pytest.approx(25.0)


def test_aircraft_converts_airfoil_camber_fraction_to_meters(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"
    cfg = load_config(config_path)

    fake_airfoil = AirfoilData(
        name="unit-test",
        x=np.array([0.0, 1.0]),
        z_upper=np.array([0.10, 0.10]),
        z_lower=np.array([0.00, 0.00]),
    )

    with patch.object(cfg.io, "airfoil_dir", tmp_path):
        with patch(
            "hpa_mdo.core.aircraft._try_load_airfoil", side_effect=[fake_airfoil, fake_airfoil]
        ):
            with patch.object(cfg.solver, "n_beam_nodes", 5):
                aircraft = Aircraft.from_config(cfg)

    expected_camber = 0.05 * aircraft.wing.chord
    np.testing.assert_allclose(aircraft.wing.main_spar_z_camber, expected_camber)
    np.testing.assert_allclose(aircraft.wing.rear_spar_z_camber, expected_camber)


def test_aircraft_builds_tail_and_fin_runtime_geometry():
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"
    cfg = load_config(config_path)

    aircraft = Aircraft.from_config(cfg)

    assert aircraft.horizontal_tail is not None
    assert aircraft.horizontal_tail.origin == pytest.approx((4.0, 0.0, 0.0))
    assert aircraft.horizontal_tail.half_span == pytest.approx(1.5)
    assert aircraft.horizontal_tail.area == pytest.approx(2.4)
    assert aircraft.horizontal_tail.control_surface_name == "elevator"

    assert aircraft.vertical_fin is not None
    assert aircraft.vertical_fin.origin == pytest.approx((5.0, 0.0, -0.7))
    assert aircraft.vertical_fin.half_span == pytest.approx(2.4)
    assert aircraft.vertical_fin.chord_at(0.5) == pytest.approx(0.7)
    assert aircraft.vertical_fin.rotation_deg == pytest.approx((90.0, 0.0, 0.0))


def test_aircraft_omits_disabled_empennage_surfaces(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["horizontal_tail"]["enabled"] = False
    data["vertical_fin"]["enabled"] = False

    cfg_path = tmp_path / "empennage_disabled.yaml"
    cfg_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    aircraft = Aircraft.from_config(load_config(cfg_path))

    assert aircraft.horizontal_tail is None
    assert aircraft.vertical_fin is None


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
