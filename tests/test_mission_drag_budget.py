"""Tests for Mission Drag Budget Contract v1."""

from __future__ import annotations

from math import isfinite
from pathlib import Path

import pytest

from hpa_mdo.mission import (
    load_csv_power_curve,
    load_rider_power_curve_metadata,
    thermal_power_derate_factor,
    RiderPowerEnvironment,
)
from hpa_mdo.mission.drag_budget import (
    MissionDragBudget,
    MissionDragBudgetInputs,
    MissionDragBudgetResult,
    load_mission_drag_budget,
    estimate_cd0_total_from_wing_budget,
    evaluate_drag_budget_candidate,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EXAMPLE_YAML = _REPO_ROOT / "configs" / "mission_drag_budget_example.yaml"
_POWER_CURVE_CSV = _REPO_ROOT / "data" / "pilot_power_curves" / "current_pilot_power_curve.csv"
_POWER_CURVE_METADATA = (
    _REPO_ROOT / "data" / "pilot_power_curves" / "current_pilot_power_curve.metadata.yaml"
)


def _reference_budget() -> MissionDragBudget:
    return load_mission_drag_budget(_EXAMPLE_YAML)


def _reference_inputs(
    *,
    cd0_wing_profile: float = 0.0125,
    rider_curve=None,
    thermal_derate_factor: float = 1.0,
    cda_override: float | None = None,
) -> tuple[MissionDragBudget, MissionDragBudgetInputs]:
    budget = _reference_budget()
    if cda_override is not None:
        budget = MissionDragBudget(
            cd0_total_target=budget.cd0_total_target,
            cd0_total_boundary=budget.cd0_total_boundary,
            cd0_total_rescue=budget.cd0_total_rescue,
            cd0_wing_profile_target=budget.cd0_wing_profile_target,
            cd0_wing_profile_boundary=budget.cd0_wing_profile_boundary,
            cda_nonwing_target_m2=cda_override,
            cda_nonwing_boundary_m2=cda_override,
            eta_prop_sizing=budget.eta_prop_sizing,
            eta_prop_target=budget.eta_prop_target,
            eta_trans=budget.eta_trans,
        )
    inputs = MissionDragBudgetInputs(
        speed_mps=6.5,
        span_m=35.0,
        aspect_ratio=38.0,
        mass_kg=98.5,
        cd0_wing_profile=cd0_wing_profile,
        oswald_e=0.90,
        cl_max_effective=1.55,
        air_density_kg_m3=1.1357,
        eta_prop=0.86,
        eta_trans=0.96,
        target_range_km=42.195,
        rider_curve=rider_curve,
        thermal_derate_factor=thermal_derate_factor,
    )
    return budget, inputs


# ---------------------------------------------------------------------------
# Test A: load_mission_drag_budget reads YAML correctly
# ---------------------------------------------------------------------------

def test_load_mission_drag_budget_reads_yaml() -> None:
    budget = load_mission_drag_budget(_EXAMPLE_YAML)

    assert budget.cd0_total_target == pytest.approx(0.017)
    assert budget.cd0_total_boundary == pytest.approx(0.018)
    assert budget.cd0_total_rescue == pytest.approx(0.020)
    assert budget.cd0_wing_profile_target == pytest.approx(0.0125)
    assert budget.cd0_wing_profile_boundary == pytest.approx(0.0140)
    assert budget.cda_nonwing_target_m2 == pytest.approx(0.13)
    assert budget.cda_nonwing_boundary_m2 == pytest.approx(0.16)
    assert budget.eta_prop_sizing == pytest.approx(0.86)
    assert budget.eta_prop_target == pytest.approx(0.88)
    assert budget.eta_trans == pytest.approx(0.96)


# ---------------------------------------------------------------------------
# Test B: estimate_cd0_total_from_wing_budget formula
# ---------------------------------------------------------------------------

def test_estimate_cd0_total_from_wing_budget_formula() -> None:
    cd0_wing = 0.0125
    wing_area_m2 = 32.0
    cda_nonwing = 0.13

    result = estimate_cd0_total_from_wing_budget(cd0_wing, wing_area_m2, cda_nonwing)

    expected = 0.0125 + 0.13 / 32.0  # 0.0165625
    assert result == pytest.approx(expected, rel=1e-9)
    assert result == pytest.approx(0.0165625, abs=1e-8)


# ---------------------------------------------------------------------------
# Test C: drag budget band classification
# ---------------------------------------------------------------------------

def test_drag_budget_band_target_case() -> None:
    # cd0_wing=0.0125, S~32.2, CDA=0.13 -> cd0_total_est ~0.01653 <= 0.017 -> target
    budget, inputs = _reference_inputs(cd0_wing_profile=0.0125)
    result = evaluate_drag_budget_candidate(budget, inputs, reserve_mode="target")

    assert result.drag_budget_band == "target"
    assert result.cd0_total_est == pytest.approx(0.0125 + 0.13 / result.wing_area_m2, rel=1e-6)
    assert result.cd0_total_target_margin > 0.0


def test_drag_budget_band_rescue_or_boundary_case() -> None:
    # cd0_wing=0.014, CDA=0.16 applied via boundary reserve_mode
    # With S~32.2: cd0_total_est = 0.014 + 0.16/32.24 ~0.0190 -> over boundary (0.018), under rescue (0.020)
    budget, inputs = _reference_inputs(cd0_wing_profile=0.014)
    result = evaluate_drag_budget_candidate(budget, inputs, reserve_mode="boundary")

    assert result.drag_budget_band in ("boundary", "rescue")


def test_drag_budget_band_over_budget_case() -> None:
    # cd0_wing=0.018, S~32.2, CDA=0.13 -> cd0_total_est = 0.018 + 0.13/32.24 ~0.022 > rescue 0.020
    budget, inputs = _reference_inputs(cd0_wing_profile=0.018)
    result = evaluate_drag_budget_candidate(budget, inputs, reserve_mode="target")

    assert result.drag_budget_band == "over_budget"
    assert result.cd0_total_est > budget.cd0_total_rescue


# ---------------------------------------------------------------------------
# Test D: reference mission candidate with real power curve
# ---------------------------------------------------------------------------

def test_reference_mission_candidate_with_real_power_curve() -> None:
    """Reference case: span=35, AR=38, mass=98.5, cd0_wing=0.0125, CDA_nonwing=0.13."""
    rider_curve = load_csv_power_curve(_POWER_CURVE_CSV)
    metadata = load_rider_power_curve_metadata(_POWER_CURVE_METADATA)
    env_raw = metadata["measurement_environment"]
    test_env = RiderPowerEnvironment(
        temperature_c=float(env_raw["temperature_c"]),
        relative_humidity_percent=float(env_raw["relative_humidity_percent"]),
    )
    race_env = RiderPowerEnvironment(temperature_c=33.0, relative_humidity_percent=80.0)
    derate = thermal_power_derate_factor(
        test_environment=test_env,
        target_environment=race_env,
        heat_loss_coefficient_per_h_c=0.008,
    )

    budget, inputs = _reference_inputs(
        cd0_wing_profile=0.0125,
        rider_curve=rider_curve,
        thermal_derate_factor=derate,
    )
    result = evaluate_drag_budget_candidate(budget, inputs, reserve_mode="target")

    # cd0_total_est should be near 0.0165 (0.0125 + 0.13/32.237...)
    assert result.cd0_total_est == pytest.approx(0.0165, abs=0.001)
    assert result.cd0_total_est < 0.017

    # All result values must be finite
    assert isfinite(result.cd0_total_est)
    assert isfinite(result.cd0_nonwing_equivalent)
    assert isfinite(result.wing_area_m2)
    assert result.mission_power_margin_crank_w is not None
    assert isfinite(result.mission_power_margin_crank_w)

    # Power margin must be substantially better than the cd0=0.020 reference case (-15 W)
    assert result.mission_power_margin_crank_w > -15.0

    # Band should be target
    assert result.drag_budget_band == "target"

    # Margins have correct sign for target band
    assert result.cd0_total_target_margin >= 0.0
    assert result.cd0_wing_profile_target_margin >= 0.0


def test_reference_candidate_margins_are_finite() -> None:
    budget, inputs = _reference_inputs(cd0_wing_profile=0.0125)
    result = evaluate_drag_budget_candidate(budget, inputs, reserve_mode="target")

    assert isfinite(result.cd0_total_target_margin)
    assert isfinite(result.cd0_total_boundary_margin)
    assert isfinite(result.cd0_wing_profile_target_margin)
    assert isfinite(result.cd0_wing_profile_boundary_margin)
    assert isfinite(result.cd0_nonwing_equivalent)


def test_reserve_mode_boundary_uses_cda_boundary() -> None:
    budget, inputs = _reference_inputs(cd0_wing_profile=0.0125)
    result_target = evaluate_drag_budget_candidate(budget, inputs, reserve_mode="target")
    result_boundary = evaluate_drag_budget_candidate(budget, inputs, reserve_mode="boundary")

    assert result_boundary.cda_nonwing_m2 == pytest.approx(budget.cda_nonwing_boundary_m2)
    assert result_target.cda_nonwing_m2 == pytest.approx(budget.cda_nonwing_target_m2)
    assert result_boundary.cd0_total_est > result_target.cd0_total_est


def test_over_budget_has_negative_target_margin() -> None:
    budget, inputs = _reference_inputs(cd0_wing_profile=0.018)
    result = evaluate_drag_budget_candidate(budget, inputs, reserve_mode="target")

    assert result.cd0_total_target_margin < 0.0
    assert result.drag_budget_band == "over_budget"
