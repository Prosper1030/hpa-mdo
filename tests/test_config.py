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
    assert cfg.io.vsp_model == (repo_root / "data/blackcat_004_origin.vsp3").resolve()
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


def test_load_config_prefers_repo_local_external_io_artifacts(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"
    overlay_path = tmp_path / "local_paths.yaml"
    sync_root = tmp_path / "SyncFile"
    overlay_path.write_text(
        f'io:\n  sync_root: "{sync_root.as_posix()}"\n',
        encoding="utf-8",
    )

    cfg = load_config(config_path, local_paths_path=overlay_path)

    assert cfg.io.vsp_model == (repo_root / "data/blackcat_004_origin.vsp3").resolve()
    assert cfg.io.vsp_lod == (
        sync_root / "Aerodynamics/black cat 004 wing only/blackcat 004 wing only_VSPGeom.lod"
    ).resolve()


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

    assert cfg.wing.airfoil_root_tc == pytest.approx(0.140)
    assert cfg.wing.airfoil_tip_tc == pytest.approx(0.117)


def test_blackcat_mission_defaults_loaded_from_config():
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"

    cfg = load_config(config_path)

    assert cfg.mission.objective_mode == "max_range"
    assert cfg.mission.target_range_km == pytest.approx(42.195)
    assert cfg.mission.speed_sweep_min_mps == pytest.approx(6.0)
    assert cfg.mission.speed_sweep_max_mps == pytest.approx(10.0)
    assert cfg.mission.speed_sweep_points == 9
    assert cfg.mission.rider_model == "fake_anchor_curve"
    assert cfg.mission.anchor_power_w == pytest.approx(300.0)
    assert cfg.mission.anchor_duration_min == pytest.approx(30.0)


def test_load_config_uses_mission_default_factory_when_section_is_absent(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data.pop("mission", None)

    cfg_path = tmp_path / "blackcat_without_mission.yaml"
    cfg_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    cfg = load_config(cfg_path)

    assert cfg.mission.objective_mode == "max_range"
    assert cfg.mission.speed_sweep_points == 9


def test_mission_override_overlay_can_change_key_fields(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"
    overlay_path = tmp_path / "local_paths.yaml"
    overlay_path.write_text(
        "mission:\n"
        "  objective_mode: min_power\n"
        "  target_range_km: 21.0\n"
        "  speed_sweep_points: 5\n",
        encoding="utf-8",
    )

    cfg = load_config(config_path, local_paths_path=overlay_path)

    assert cfg.mission.objective_mode == "min_power"
    assert cfg.mission.target_range_km == pytest.approx(21.0)
    assert cfg.mission.speed_sweep_points == 5


def test_load_config_rejects_inverted_mission_speed_sweep_bounds(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"
    overlay_path = tmp_path / "local_paths.yaml"
    overlay_path.write_text(
        "mission:\n"
        "  speed_sweep_min_mps: 10.0\n"
        "  speed_sweep_max_mps: 6.0\n",
        encoding="utf-8",
    )

    with pytest.raises(ValidationError, match=r"mission\.speed_sweep_max_mps must exceed mission\.speed_sweep_min_mps"):
        load_config(config_path, local_paths_path=overlay_path)


def test_blackcat_lift_wire_angle_loaded_from_config():
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"

    cfg = load_config(config_path)

    assert cfg.lift_wires.wire_angle_deg == pytest.approx(11.3)


def test_blackcat_lift_wire_pretension_defaults_to_zero():
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"

    cfg = load_config(config_path)

    assert cfg.lift_wires.attachment_pretensions_n() == [0.0]


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


def test_multi_wire_layout_expands_scalar_or_list_pretension_values(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["lift_wires"]["attachments"] = [
        {"y": 4.5, "fuselage_z": -1.5, "label": "wire-1"},
        {"y": 10.5, "fuselage_z": -1.5, "label": "wire-2"},
    ]
    data["lift_wires"]["pretension_n"] = 120.0

    cfg_path = tmp_path / "multi_wire_scalar_pretension.yaml"
    cfg_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    cfg = load_config(cfg_path)
    assert cfg.lift_wires.attachment_pretensions_n() == [120.0, 120.0]

    data["lift_wires"]["pretension_n"] = [100.0, 180.0]
    cfg_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    cfg = load_config(cfg_path)
    assert cfg.lift_wires.attachment_pretensions_n() == [100.0, 180.0]


def test_multi_wire_layout_rejects_mismatched_pretension_list(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["lift_wires"]["attachments"] = [
        {"y": 4.5, "fuselage_z": -1.5, "label": "wire-1"},
        {"y": 10.5, "fuselage_z": -1.5, "label": "wire-2"},
    ]
    data["lift_wires"]["pretension_n"] = [100.0]

    cfg_path = tmp_path / "multi_wire_bad_pretension.yaml"
    cfg_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValueError, match="pretension_n list must align"):
        load_config(cfg_path)


def test_blackcat_loaded_shape_tolerances_loaded_from_solver_config():
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"

    cfg = load_config(config_path)

    assert cfg.solver.loaded_shape_z_tol_m == pytest.approx(0.025)
    assert cfg.solver.loaded_shape_twist_tol_deg == pytest.approx(0.15)


def test_aircraft_from_config_uses_wing_chord_dihedral_and_twist_schedules(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data["io"]["airfoil_dir"] = None
    data["wing"]["span"] = 33.0
    data["wing"]["root_chord"] = 1.2
    data["wing"]["tip_chord"] = 0.6
    data["wing"]["chord_schedule"] = [
        [0.0, 1.2],
        [8.25, 1.0],
        [16.5, 0.6],
    ]
    data["wing"]["dihedral_schedule"] = [
        [0.0, 0.0],
        [8.25, 0.4],
        [16.5, 1.0],
    ]
    data["wing"]["twist_schedule"] = [
        [0.0, 2.0],
        [16.5, 0.0],
    ]

    cfg_path = tmp_path / "scheduled_wing.yaml"
    cfg_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    cfg = load_config(cfg_path)
    aircraft = Aircraft.from_config(cfg)

    mid_idx = int(np.argmin(np.abs(aircraft.wing.y - 8.25)))
    expected_mid_chord = np.interp(
        aircraft.wing.y[mid_idx],
        [0.0, 8.25, 16.5],
        [1.2, 1.0, 0.6],
    )
    assert aircraft.wing.chord[mid_idx] == pytest.approx(expected_mid_chord)
    assert aircraft.wing.loaded_z_m is not None
    expected_mid_z = np.interp(
        aircraft.wing.y[mid_idx],
        [0.0, 8.25, 16.5],
        [0.0, 0.4, 1.0],
    )
    assert aircraft.wing.loaded_z_m[mid_idx] == pytest.approx(expected_mid_z)
    assert aircraft.wing.loaded_z_m[-1] == pytest.approx(1.0)
    assert aircraft.wing.twist_deg[0] == pytest.approx(2.0)
    assert aircraft.wing.twist_deg[-1] == pytest.approx(0.0)
    assert aircraft.wing.dihedral_deg[0] == pytest.approx(
        np.degrees(np.arctan2(0.4, 8.25)),
        abs=0.2,
    )
    assert aircraft.wing.dihedral_deg[-1] == pytest.approx(
        np.degrees(np.arctan2(0.6, 8.25)),
        abs=0.2,
    )

    spar_dx_tip = (
        cfg.rear_spar.location_xc - cfg.main_spar.location_xc
    ) * aircraft.wing.chord[-1]
    expected_rear_offset_tip = spar_dx_tip * np.tan(np.radians(-2.0))
    assert aircraft.wing.rear_spar_z_camber[-1] == pytest.approx(
        expected_rear_offset_tip
    )


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
    assert cfg.main_spar.max_ply_drop_per_segment == 1
    assert cfg.main_spar.min_layup_run_length_m == pytest.approx(1.5)
    assert cfg.rear_spar.layup_mode == "isotropic"
    assert cfg.rear_spar.ply_material == "cfrp_ply_hm"
    assert cfg.rear_spar.max_ply_drop_per_segment == 1
    assert cfg.rear_spar.min_layup_run_length_m == pytest.approx(1.5)


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
    assert cfg.horizontal_tail.span == pytest.approx(4.0)
    assert cfg.horizontal_tail.symmetry == "xz"
    assert cfg.horizontal_tail.control_surface_limit_deg == pytest.approx(20.0)

    assert cfg.vertical_fin.name == "Fin"
    assert cfg.vertical_fin.z_location == pytest.approx(-0.7)
    assert cfg.vertical_fin.x_rotation_deg == pytest.approx(90.0)
    assert cfg.vertical_fin.control_surface_limit_deg == pytest.approx(25.0)


def test_blackcat_mass_budget_loaded_from_config():
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "configs" / "blackcat_004.yaml"

    cfg = load_config(config_path)

    assert cfg.mass_budget.target_total_mass_kg == pytest.approx(96.0)
    assert cfg.mass_budget.pilot is not None
    assert cfg.mass_budget.pilot.m_kg == pytest.approx(56.0)
    assert cfg.mass_budget.drivetrain is not None
    assert cfg.mass_budget.drivetrain.xyz_m == pytest.approx([0.8, 0.0, -0.25])
    assert "telemetry_spare" in cfg.mass_budget.extra_items


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
    assert aircraft.horizontal_tail.origin == pytest.approx((6.5, 0.0, 0.0))
    assert aircraft.horizontal_tail.half_span == pytest.approx(2.0)
    assert aircraft.horizontal_tail.area == pytest.approx(3.6)
    assert aircraft.horizontal_tail.control_surface_name == "elevator"

    assert aircraft.vertical_fin is not None
    assert aircraft.vertical_fin.origin == pytest.approx((7.0, 0.0, -0.7))
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
