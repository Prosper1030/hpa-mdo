from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import numpy as np

from hpa_mdo.core.aircraft import Aircraft
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
