from __future__ import annotations

from pathlib import Path

import numpy as np

from hpa_mdo.core.config import load_config
from hpa_mdo.structure.optimizer import OptimizationResult
from hpa_mdo.utils.data_collector import DataCollector


def _segments(n: int) -> list[float]:
    return [16.5 / n] * n


def _fake_result(n_main: int, n_rear: int) -> OptimizationResult:
    return OptimizationResult(
        success=True,
        message="ok",
        spar_mass_half_kg=1.0,
        spar_mass_full_kg=2.0,
        total_mass_full_kg=2.5,
        max_stress_main_Pa=1.0e8,
        max_stress_rear_Pa=0.8e8,
        allowable_stress_main_Pa=2.0e8,
        allowable_stress_rear_Pa=2.0e8,
        failure_index=-0.2,
        buckling_index=-0.3,
        tip_deflection_m=0.15,
        max_tip_deflection_m=2.5,
        twist_max_deg=0.9,
        main_t_seg_mm=np.full(n_main, 1.2),
        main_r_seg_mm=np.full(n_main, 35.0),
        rear_t_seg_mm=np.full(n_rear, 1.0) if n_rear > 0 else None,
        rear_r_seg_mm=np.full(n_rear, 25.0) if n_rear > 0 else None,
    )


def test_data_collector_uses_dynamic_segment_columns(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    cfg = load_config(repo_root / "configs" / "blackcat_004.yaml")
    cfg.main_spar.segments = _segments(5)
    cfg.rear_spar.segments = _segments(5)

    db_path = tmp_path / "training.csv"
    collector = DataCollector(str(db_path))
    collector.record(cfg, _fake_result(5, 5))

    header = db_path.read_text(encoding="utf-8").splitlines()[0].split(",")
    assert "main_t_seg_5" in header
    assert "rear_t_seg_5" in header
    assert "main_t_seg_6" not in header
    assert "rear_t_seg_6" not in header
    assert "buckling_index" in header

    df = collector.load()
    assert df.loc[0, "buckling_index"] == -0.3


def test_data_collector_merges_columns_when_segment_count_grows(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "training.csv"
    collector = DataCollector(str(db_path))

    cfg_6 = load_config(repo_root / "configs" / "blackcat_004.yaml")
    cfg_6.main_spar.segments = _segments(6)
    cfg_6.rear_spar.segments = _segments(6)
    collector.record(cfg_6, _fake_result(6, 6))

    cfg_7 = load_config(repo_root / "configs" / "blackcat_004.yaml")
    cfg_7.main_spar.segments = _segments(7)
    cfg_7.rear_spar.segments = _segments(7)
    collector.record(cfg_7, _fake_result(7, 7))

    df = collector.load()
    assert "main_t_seg_7" in df.columns
    assert "rear_t_seg_7" in df.columns
    assert len(df) == 2
