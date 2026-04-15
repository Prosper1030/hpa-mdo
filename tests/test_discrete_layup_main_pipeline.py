"""Smoke tests for the --discrete-layup main pipeline wiring (F-Layup)."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples"))

from blackcat_004_optimize import main as run_optimize  # noqa: E402


@pytest.mark.slow
def test_discrete_layup_main_pipeline_runs(tmp_path):
    """``--discrete-layup`` runs end-to-end and writes the layup schedule."""
    val_weight = run_optimize(["--discrete-layup"])
    assert isinstance(val_weight, float)
    assert math.isfinite(val_weight)

    summary_path = ROOT / "output" / "blackcat_004" / "optimization_summary.txt"
    assert summary_path.exists(), f"missing summary: {summary_path}"
    text = summary_path.read_text(encoding="utf-8")
    assert "DISCRETE LAYUP SCHEDULE" in text
    assert "Main spar:" in text


@pytest.mark.slow
def test_discrete_layup_strength_ratios_safe():
    """Every segment stack has Tsai-Wu strength ratio >= 1.0 (SAFE)."""
    from hpa_mdo.core import load_config, Aircraft, MaterialDB
    from hpa_mdo.structure import SparOptimizer
    from hpa_mdo.aero import VSPAeroParser, LoadMapper
    from hpa_mdo.utils.discrete_layup import (
        build_segment_layup_results,
        enumerate_valid_stacks,
    )

    cfg = load_config(ROOT / "configs" / "blackcat_004.yaml")
    ac = Aircraft.from_config(cfg)
    mat_db = MaterialDB()
    parser = VSPAeroParser(cfg.io.vsp_lod, cfg.io.vsp_polar)
    cases = parser.parse()
    mapper = LoadMapper()
    best = None
    best_res = float("inf")
    for case in cases:
        loads = mapper.map_loads(
            case, ac.wing.y,
            actual_velocity=cfg.flight.velocity,
            actual_density=cfg.flight.air_density,
        )
        res = abs(2.0 * loads["total_lift"] - ac.weight_N)
        if res < best_res:
            best_res = res
            best = loads
    opt = SparOptimizer(cfg, ac, best, mat_db)
    result = opt.optimize(method="auto")

    ply_mat = mat_db.get_ply(cfg.main_spar.ply_material)
    stacks = enumerate_valid_stacks(cfg.main_spar)
    seg_lengths = cfg.spar_segment_lengths(cfg.main_spar)
    n_seg = len(seg_lengths)
    env = result.strain_envelope or {}
    strain_envs = [
        {
            "epsilon_x_absmax": float(env.get("epsilon_x_absmax", [0] * n_seg)[i]),
            "kappa_absmax": float(env.get("kappa_absmax", [0] * n_seg)[i]),
            "torsion_rate_absmax": float(env.get("torsion_rate_absmax", [0] * n_seg)[i]),
        }
        for i in range(n_seg)
    ]
    layup = build_segment_layup_results(
        segment_lengths_m=seg_lengths,
        continuous_thicknesses_m=(result.main_t_seg_mm / 1000.0).tolist(),
        outer_radii_m=(result.main_r_seg_mm / 1000.0).tolist(),
        stacks=stacks,
        ply_mat=ply_mat,
        ply_drop_limit=int(cfg.main_spar.max_ply_drop_per_segment),
        strain_envelopes=strain_envs,
    )
    for seg in layup:
        tw = seg.tsai_wu_summary
        assert tw is not None, f"seg {seg.segment_index} missing Tsai-Wu summary"
        assert tw.min_strength_ratio >= 1.0, (
            f"seg {seg.segment_index}: SR={tw.min_strength_ratio:.3f} < 1.0"
        )
