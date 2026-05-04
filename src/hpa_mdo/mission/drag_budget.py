"""Mission drag budget contract v1.

Separates main-wing profile CD0 from non-wing parasite drag so the wing
optimizer can be given a focused CD0 target without needing to know the
whole-aircraft drag breakdown.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Literal, Optional

import yaml

from .objective import CsvPowerCurve, FakeAnchorCurve
from .quick_screen import MissionQuickScreenInputs, evaluate_quick_screen


RiderCurve = FakeAnchorCurve | CsvPowerCurve

DragBudgetBand = Literal["target", "boundary", "rescue", "over_budget"]


@dataclass(frozen=True)
class MissionDragBudget:
    """Contract values loaded from a mission_drag_budget YAML."""

    cd0_total_target: float
    cd0_total_boundary: float
    cd0_total_rescue: float
    cd0_wing_profile_target: float
    cd0_wing_profile_boundary: float
    cda_nonwing_target_m2: float
    cda_nonwing_boundary_m2: float
    eta_prop_sizing: float
    eta_prop_target: float
    eta_trans: float


@dataclass(frozen=True)
class MissionDragBudgetInputs:
    """Per-candidate inputs for drag budget evaluation."""

    speed_mps: float
    span_m: float
    aspect_ratio: float
    mass_kg: float
    cd0_wing_profile: float
    oswald_e: float
    cl_max_effective: float
    air_density_kg_m3: float
    eta_prop: float
    eta_trans: float
    target_range_km: float
    rider_curve: Optional[RiderCurve]
    thermal_derate_factor: float


@dataclass(frozen=True)
class MissionDragBudgetResult:
    """Outcome of one drag budget evaluation."""

    wing_area_m2: float
    cd0_wing_profile: float
    cda_nonwing_m2: float
    cd0_nonwing_equivalent: float
    cd0_total_est: float
    cd0_total_target_margin: float
    cd0_total_boundary_margin: float
    cd0_wing_profile_target_margin: float
    cd0_wing_profile_boundary_margin: float
    mission_power_margin_crank_w: Optional[float]
    power_passed: Optional[bool]
    robust_passed: bool
    drag_budget_band: DragBudgetBand


def load_mission_drag_budget(path: Path | str) -> MissionDragBudget:
    """Parse a mission_drag_budget YAML and return a MissionDragBudget."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    total = raw["total_drag_budget"]
    wing = raw["main_wing_budget"]
    nonwing = raw["nonwing_reserve"]
    prop = raw["propulsion_budget"]
    return MissionDragBudget(
        cd0_total_target=float(total["cd0_total_target"]),
        cd0_total_boundary=float(total["cd0_total_boundary"]),
        cd0_total_rescue=float(total["cd0_total_rescue"]),
        cd0_wing_profile_target=float(wing["cd0_profile_target"]),
        cd0_wing_profile_boundary=float(wing["cd0_profile_boundary"]),
        cda_nonwing_target_m2=float(nonwing["cda_target_m2"]),
        cda_nonwing_boundary_m2=float(nonwing["cda_boundary_m2"]),
        eta_prop_sizing=float(prop["eta_prop_sizing"]),
        eta_prop_target=float(prop["eta_prop_target"]),
        eta_trans=float(prop["eta_trans"]),
    )


def estimate_cd0_total_from_wing_budget(
    cd0_wing_profile: float,
    wing_area_m2: float,
    cda_nonwing_m2: float,
) -> float:
    """Estimate whole-aircraft CD0 by adding a non-wing CDA reserve.

    CD0_total_est = CD0_wing_profile + CDA_nonwing / S
    """
    return cd0_wing_profile + cda_nonwing_m2 / wing_area_m2


def evaluate_drag_budget_candidate(
    budget: MissionDragBudget,
    inputs: MissionDragBudgetInputs,
    reserve_mode: str = "target",
) -> MissionDragBudgetResult:
    """Evaluate a single wing-design candidate against the drag budget.

    Args:
        budget: Contract limits loaded from YAML.
        inputs: Per-candidate aerodynamic and mission parameters.
        reserve_mode: ``"target"`` uses cda_nonwing_target_m2;
            ``"boundary"`` uses cda_nonwing_boundary_m2.

    Returns:
        Full drag budget result including band classification and power
        margin from the mission quick-screen.
    """
    wing_area_m2 = inputs.span_m**2 / inputs.aspect_ratio

    if reserve_mode == "boundary":
        cda_nonwing_m2 = budget.cda_nonwing_boundary_m2
    else:
        cda_nonwing_m2 = budget.cda_nonwing_target_m2

    cd0_total_est = estimate_cd0_total_from_wing_budget(
        inputs.cd0_wing_profile, wing_area_m2, cda_nonwing_m2
    )
    cd0_nonwing_equivalent = cda_nonwing_m2 / wing_area_m2

    qs_inputs = MissionQuickScreenInputs(
        speed_mps=inputs.speed_mps,
        span_m=inputs.span_m,
        aspect_ratio=inputs.aspect_ratio,
        mass_kg=inputs.mass_kg,
        cd0_total=cd0_total_est,
        oswald_e=inputs.oswald_e,
        air_density_kg_m3=inputs.air_density_kg_m3,
        eta_prop=inputs.eta_prop,
        eta_trans=inputs.eta_trans,
        target_range_km=inputs.target_range_km,
        rider_curve=inputs.rider_curve,
        thermal_derate_factor=inputs.thermal_derate_factor,
        cl_max_effective=inputs.cl_max_effective,
    )
    qsr = evaluate_quick_screen(qs_inputs)

    drag_budget_band = _classify_drag_budget_band(
        cd0_total_est=cd0_total_est,
        cd0_wing_profile=inputs.cd0_wing_profile,
        budget=budget,
    )

    robust_passed = _evaluate_robust(qsr)

    return MissionDragBudgetResult(
        wing_area_m2=float(wing_area_m2),
        cd0_wing_profile=float(inputs.cd0_wing_profile),
        cda_nonwing_m2=float(cda_nonwing_m2),
        cd0_nonwing_equivalent=float(cd0_nonwing_equivalent),
        cd0_total_est=float(cd0_total_est),
        cd0_total_target_margin=float(budget.cd0_total_target - cd0_total_est),
        cd0_total_boundary_margin=float(budget.cd0_total_boundary - cd0_total_est),
        cd0_wing_profile_target_margin=float(
            budget.cd0_wing_profile_target - inputs.cd0_wing_profile
        ),
        cd0_wing_profile_boundary_margin=float(
            budget.cd0_wing_profile_boundary - inputs.cd0_wing_profile
        ),
        mission_power_margin_crank_w=qsr.power_margin_crank_w,
        power_passed=qsr.power_passed,
        robust_passed=robust_passed,
        drag_budget_band=drag_budget_band,
    )


def _classify_drag_budget_band(
    cd0_total_est: float,
    cd0_wing_profile: float,
    budget: MissionDragBudget,
) -> DragBudgetBand:
    if (
        cd0_total_est <= budget.cd0_total_target
        and cd0_wing_profile <= budget.cd0_wing_profile_target
    ):
        return "target"
    if (
        cd0_total_est <= budget.cd0_total_boundary
        and cd0_wing_profile <= budget.cd0_wing_profile_boundary
    ):
        return "boundary"
    if cd0_total_est <= budget.cd0_total_rescue:
        return "rescue"
    return "over_budget"


def _evaluate_robust(qsr) -> bool:  # type: ignore[no-untyped-def]
    if qsr.power_passed is not True:
        return False
    if qsr.power_margin_crank_w is None or qsr.power_margin_crank_w < 5.0:
        return False
    if qsr.cl_band != "normal":
        return False
    if qsr.stall_band not in ("healthy", "caution"):
        return False
    if qsr.cl_to_clmax_ratio > 0.90:
        return False
    return True
