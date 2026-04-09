"""End-to-end regression: Black Cat 004 baseline mass and constraints.

This test runs the full optimization pipeline (config -> VSPAero parse ->
LoadMapper -> SparOptimizer.optimize) on the canonical blackcat_004.yaml
and asserts the result matches a frozen baseline within engineering
tolerance.

It exists to catch silent physics regressions that unit tests cannot:
KS aggregation parameters changing, dependency upgrades shifting DE
behavior, knockdown factor edits, etc.

When this test fails:
1. If the change is intentional and the new mass is engineering-correct,
   update the BASELINE_* constants below and add a one-line note in the
   commit message explaining what changed and why.
2. If the change is unintentional, find and revert the offending edit.

Marked @pytest.mark.slow - runs the full DE+SLSQP loop. Run with
`pytest -m slow tests/test_golden_blackcat_004.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hpa_mdo.aero.load_mapper import LoadMapper
from hpa_mdo.aero.vsp_aero import VSPAeroParser
from hpa_mdo.core.aircraft import Aircraft
from hpa_mdo.core.config import load_config
from hpa_mdo.core.materials import MaterialDB
from hpa_mdo.structure.optimizer import SparOptimizer


REPO_ROOT = Path(__file__).resolve().parents[1]


# Frozen baseline (Milestone 1 + main spar dominance).
# Generated: 2026-04-08
# Last updated by: a25ae3e (M5 golden value test initialization)
# Run on: macOS / Python 3.10.18 / numpy 2.2.6 / scipy 1.15.3
BASELINE_TOTAL_MASS_KG = 21.5658
BASELINE_FAILURE_INDEX = -0.68210
BASELINE_BUCKLING_INDEX = -0.85250
BASELINE_TIP_DEFLECTION_M = 1.85389
BASELINE_TWIST_MAX_DEG = 0.125

BASELINE_TOTAL_MASS_TOL_KG = 0.30  # ±2% design target (tightened absolute cap)

# Constraints that must hold (these are physics, not stochastic).
MAX_FAILURE_INDEX = 0.01
MAX_BUCKLING_INDEX = 0.01
MAX_TIP_DEFLECTION_RATIO = 1.02  # tolerate 2% over max (SLSQP boundary slop)
MAX_TWIST_MARGIN_DEG = 0.05  # tolerate 0.05° over max twist


@pytest.mark.slow
@pytest.mark.requires_vspaero
def test_blackcat_004_baseline_mass_and_constraints() -> None:
    cfg = load_config(REPO_ROOT / "configs" / "blackcat_004.yaml")
    missing_assets = [
        str(path)
        for path in (cfg.io.vsp_lod, cfg.io.vsp_polar)
        if path is not None and not Path(path).exists()
    ]
    if missing_assets:
        pytest.skip(
            "Missing VSPAero test assets required for golden regression: "
            + ", ".join(missing_assets)
        )

    aircraft = Aircraft.from_config(cfg)
    mat_db = MaterialDB()

    target_weight = aircraft.weight_N

    parser = VSPAeroParser(cfg.io.vsp_lod, cfg.io.vsp_polar)
    aero_cases = parser.parse()
    assert len(aero_cases) > 0, "VSPAero parser returned no cases"

    mapper = LoadMapper()
    best_residual = float("inf")
    best_loads = None

    for aero in aero_cases:
        loads = mapper.map_loads(
            aero,
            aircraft.wing.y,
            actual_velocity=cfg.flight.velocity,
            actual_density=cfg.flight.air_density,
        )
        full_lift = 2.0 * loads["total_lift"]
        residual = abs(full_lift - target_weight)
        if residual < best_residual:
            best_residual = residual
            best_loads = loads

    assert best_loads is not None, "Failed to map loads for all VSPAero cases"
    design_loads = LoadMapper.apply_load_factor(
        best_loads, cfg.safety.aerodynamic_load_factor
    )

    optimizer = SparOptimizer(cfg, aircraft, design_loads, mat_db)
    result = optimizer.optimize(method="scipy")

    # Mass: ±2% of frozen baseline (absolute cap 0.30 kg).
    mass_delta = abs(result.total_mass_full_kg - BASELINE_TOTAL_MASS_KG)
    assert mass_delta <= BASELINE_TOTAL_MASS_TOL_KG, (
        "\nBlack Cat 004 baseline mass regression detected:\n"
        f"  Current : {result.total_mass_full_kg:.4f} kg\n"
        f"  Baseline: {BASELINE_TOTAL_MASS_KG:.4f} kg\n"
        f"  Delta   : {mass_delta:.4f} kg "
        f"(tolerance ±{BASELINE_TOTAL_MASS_TOL_KG:.2f} kg)\n\n"
        "If this change is intentional, update the BASELINE_* constants in\n"
        "this file and explain the reason in the commit message.\n"
        "If unintentional, find and revert the offending physics change."
    )

    # Constraints: hard physical limits.
    assert result.failure_index <= MAX_FAILURE_INDEX, (
        f"failure_index = {result.failure_index:.5f} > {MAX_FAILURE_INDEX:.2f} "
        "(stress constraint violated)"
    )
    assert result.buckling_index <= MAX_BUCKLING_INDEX, (
        f"buckling_index = {result.buckling_index:.5f} > {MAX_BUCKLING_INDEX:.2f} "
        "(shell buckling constraint violated)"
    )

    if cfg.wing.max_tip_deflection_m is not None:
        max_deflection_m = cfg.wing.max_tip_deflection_m
        deflection_ratio = result.tip_deflection_m / max_deflection_m
        assert deflection_ratio <= MAX_TIP_DEFLECTION_RATIO, (
            f"tip_deflection = {result.tip_deflection_m:.5f} m "
            f"({deflection_ratio*100:.2f}% of limit), "
            f"exceeds {MAX_TIP_DEFLECTION_RATIO*100:.0f}% tolerance"
        )

    twist_limit = cfg.wing.max_tip_twist_deg + MAX_TWIST_MARGIN_DEG
    assert result.twist_max_deg <= twist_limit, (
        f"twist_max = {result.twist_max_deg:.3f} deg > {twist_limit:.3f} deg "
        f"(twist constraint violated, including {MAX_TWIST_MARGIN_DEG:.2f} deg slop)"
    )
