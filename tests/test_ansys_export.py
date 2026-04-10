from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import re

import numpy as np

from hpa_mdo.core.aircraft import AirfoilData, Aircraft
from hpa_mdo.core.config import load_config
from hpa_mdo.core.materials import MaterialDB
from hpa_mdo.structure.ansys_export import ANSYSExporter
from hpa_mdo.structure.optimizer import OptimizationResult
from hpa_mdo.structure.spar_model import compute_outer_radius, segment_boundaries_from_lengths


def _build_result(
    n_seg: int,
    main_r_seg_mm: np.ndarray,
    rear_r_seg_mm: np.ndarray,
) -> OptimizationResult:
    return OptimizationResult(
        success=True,
        message="ok",
        spar_mass_half_kg=1.0,
        spar_mass_full_kg=2.0,
        total_mass_full_kg=2.5,
        max_stress_main_Pa=80e6,
        max_stress_rear_Pa=65e6,
        allowable_stress_main_Pa=300e6,
        allowable_stress_rear_Pa=300e6,
        failure_index=-0.2,
        buckling_index=-0.2,
        tip_deflection_m=0.2,
        max_tip_deflection_m=2.5,
        twist_max_deg=1.0,
        main_t_seg_mm=np.full(n_seg, 1.2),
        main_r_seg_mm=main_r_seg_mm,
        rear_t_seg_mm=np.full(n_seg, 0.9),
        rear_r_seg_mm=rear_r_seg_mm,
        disp=np.zeros((10, 6)),
        vonmises_main=np.zeros(9),
        vonmises_rear=np.zeros(9),
    )


def _segment_mm_to_node_m(
    seg_values_mm: np.ndarray,
    seg_lengths: list[float],
    y_nodes: np.ndarray,
) -> np.ndarray:
    boundaries = segment_boundaries_from_lengths(seg_lengths)
    out = np.empty_like(y_nodes, dtype=float)
    for i, yy in enumerate(y_nodes):
        idx = int(np.searchsorted(boundaries[1:], yy, side="right"))
        idx = min(idx, len(seg_values_mm) - 1)
        out[i] = seg_values_mm[idx] * 1e-3
    return out


def test_ansys_exporter_prefers_optimized_radii():
    repo_root = Path(__file__).resolve().parents[1]
    cfg = load_config(repo_root / "configs" / "blackcat_004.yaml")
    with patch.object(cfg.solver, "n_beam_nodes", 10):
        aircraft = Aircraft.from_config(cfg)

    n_seg = len(cfg.spar_segment_lengths(cfg.main_spar))
    main_r_seg_mm = np.linspace(9.0, 14.0, n_seg)
    rear_r_seg_mm = np.linspace(7.0, 11.0, n_seg)
    result = _build_result(n_seg, main_r_seg_mm, rear_r_seg_mm)
    nn = aircraft.wing.n_stations
    aero_loads = {
        "lift_per_span": np.zeros(nn),
        "torque_per_span": np.zeros(nn),
    }

    exporter = ANSYSExporter(cfg, aircraft, result, aero_loads, MaterialDB())

    main_seg_lengths = cfg.spar_segment_lengths(cfg.main_spar)
    rear_seg_lengths = cfg.spar_segment_lengths(cfg.rear_spar)
    expected_main = _segment_mm_to_node_m(main_r_seg_mm, main_seg_lengths, aircraft.wing.y)
    expected_rear = _segment_mm_to_node_m(rear_r_seg_mm, rear_seg_lengths, aircraft.wing.y)

    np.testing.assert_allclose(exporter.R_main, expected_main)
    np.testing.assert_allclose(exporter.R_rear, expected_rear)

    fallback_main = compute_outer_radius(
        aircraft.wing.y, aircraft.wing.chord, aircraft.wing.airfoil_thickness, cfg.main_spar
    )
    assert not np.allclose(expected_main, fallback_main)


def test_ansys_exporter_uses_physical_camber_offsets_without_extra_chord_factor():
    repo_root = Path(__file__).resolve().parents[1]
    cfg = load_config(repo_root / "configs" / "blackcat_004.yaml")
    fake_airfoil = AirfoilData(
        name="unit-test",
        x=np.array([0.0, 1.0]),
        z_upper=np.array([0.10, 0.10]),
        z_lower=np.array([0.00, 0.00]),
    )
    with patch("hpa_mdo.core.aircraft._try_load_airfoil", side_effect=[fake_airfoil, fake_airfoil]):
        with patch.object(cfg.solver, "n_beam_nodes", 10):
            aircraft = Aircraft.from_config(cfg)

    n_seg = len(cfg.spar_segment_lengths(cfg.main_spar))
    result = _build_result(
        n_seg,
        np.full(n_seg, 12.0),
        np.full(n_seg, 9.0),
    )
    aero_loads = {
        "lift_per_span": np.zeros(aircraft.wing.n_stations),
        "torque_per_span": np.zeros(aircraft.wing.n_stations),
    }

    exporter = ANSYSExporter(cfg, aircraft, result, aero_loads, MaterialDB())

    np.testing.assert_allclose(exporter.z_main - exporter.z_dih, aircraft.wing.main_spar_z_camber)
    np.testing.assert_allclose(exporter.z_rear - exporter.z_dih, aircraft.wing.rear_spar_z_camber)


def test_ansys_apdl_accumulates_fz_loads_without_overwrite(tmp_path):
    """APDL writer must emit one FK,node,FZ line per node after accumulation."""
    repo_root = Path(__file__).resolve().parents[1]
    cfg = load_config(repo_root / "configs" / "blackcat_004.yaml")
    with patch.object(cfg.solver, "n_beam_nodes", 10):
        aircraft = Aircraft.from_config(cfg)

    n_seg = len(cfg.spar_segment_lengths(cfg.main_spar))
    result = _build_result(
        n_seg,
        np.full(n_seg, 12.0),
        np.full(n_seg, 9.0),
    )

    y = aircraft.wing.y
    nn = aircraft.wing.n_stations
    lift = np.linspace(30.0, 10.0, nn)
    torque = np.linspace(-20.0, -5.0, nn)
    aero_loads = {
        "lift_per_span": lift,
        "torque_per_span": torque,
    }

    exporter = ANSYSExporter(cfg, aircraft, result, aero_loads, MaterialDB())
    path = exporter.write_apdl(tmp_path / "spar_model.mac")
    apdl_text = path.read_text(encoding="utf-8")

    fk_matches = re.findall(
        r"^FK,\s*(\d+)\s*,\s*FZ,\s*([+-]?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)",
        apdl_text,
        flags=re.MULTILINE,
    )
    assert fk_matches, "No FK,* ,FZ commands found in APDL macro."

    # Ensure there is no duplicate FZ assignment per node.
    node_ids = [int(node) for node, _ in fk_matches]
    assert len(node_ids) == len(set(node_ids))

    # Verify accumulated loads equal analytical nodal sums.
    dy = np.diff(y)
    expected_main = np.zeros(nn, dtype=float)
    expected_rear = np.zeros(nn, dtype=float)
    for j in range(nn):
        if j == 0:
            expected_main[j] += lift[j] * dy[0] / 2.0
            m_node = torque[j] * dy[0] / 2.0
        elif j == nn - 1:
            expected_main[j] += lift[j] * dy[-1] / 2.0
            m_node = torque[j] * dy[-1] / 2.0
        else:
            expected_main[j] += lift[j] * (dy[j - 1] + dy[j]) / 2.0
            m_node = torque[j] * (dy[j - 1] + dy[j]) / 2.0

        sep = exporter.x_rear[j] - exporter.x_main[j]
        if abs(sep) > 1e-6:
            fz_couple = m_node / sep
            expected_main[j] += fz_couple
            expected_rear[j] -= fz_couple

    observed = {int(node): float(val) for node, val in fk_matches}
    for j in range(nn):
        node_main = j + 1
        node_rear = nn + j + 1
        if abs(expected_main[j]) > 1e-10:
            assert node_main in observed
            np.testing.assert_allclose(observed[node_main], expected_main[j], atol=1e-6)
        if abs(expected_rear[j]) > 1e-10:
            assert node_rear in observed
            np.testing.assert_allclose(observed[node_rear], expected_rear[j], atol=1e-6)


def test_ansys_apdl_post_commands_are_beam188_compatible(tmp_path):
    """APDL post section should avoid invalid S,EQV extraction for beam elements."""
    repo_root = Path(__file__).resolve().parents[1]
    cfg = load_config(repo_root / "configs" / "blackcat_004.yaml")
    with patch.object(cfg.solver, "n_beam_nodes", 10):
        aircraft = Aircraft.from_config(cfg)

    n_seg = len(cfg.spar_segment_lengths(cfg.main_spar))
    result = _build_result(
        n_seg,
        np.full(n_seg, 12.0),
        np.full(n_seg, 9.0),
    )
    aero_loads = {
        "lift_per_span": np.zeros(aircraft.wing.n_stations),
        "torque_per_span": np.zeros(aircraft.wing.n_stations),
    }
    exporter = ANSYSExporter(cfg, aircraft, result, aero_loads, MaterialDB())
    path = exporter.write_apdl(tmp_path / "spar_model.mac")
    apdl_text = path.read_text(encoding="utf-8")

    assert "ESEL,S,TYPE,,1,2" in apdl_text
    assert "ETABLE,VM_I,SMISC,31" in apdl_text
    assert "ETABLE,VM_J,SMISC,36" in apdl_text
    assert "PRRSOL,FZ" in apdl_text
    assert "ETABLE,VONM,S,EQV" not in apdl_text
    assert "PRESOL,SMISC" not in apdl_text
    assert "*GET,UZ_MAX,NODE,0,U,Z,MAX" not in apdl_text
    assert "*GET,UZ_MIN,NODE,0,U,Z,MIN" not in apdl_text
