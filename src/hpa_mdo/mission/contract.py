"""Mission contract adapter for upstream concept optimizers.

This module converts mission screener seed rows and drag-budget context into a
single additive contract object.  It is intentionally passive: callers can
export the values for audit/shadow use without changing candidate ranking or
gate behavior.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Mapping


G_MPS2 = 9.80665

MISSION_CONTRACT_SHADOW_FIELDS = (
    "mission_CL_req",
    "mission_CD_wing_profile_target",
    "mission_CD_wing_profile_boundary",
    "mission_CDA_nonwing_target_m2",
    "mission_CDA_nonwing_boundary_m2",
    "mission_power_margin_required_w",
    "mission_contract_source",
)


@dataclass(frozen=True)
class MissionContract:
    speed_mps: float
    span_m: float
    aspect_ratio: float
    wing_area_m2: float
    mass_kg: float
    weight_n: float
    rho: float
    CL_req: float
    target_range_km: float
    required_time_min: float
    eta_prop: float
    eta_trans: float
    pilot_power_hot_w: float | None
    power_margin_required_w: float
    CD0_total_target: float
    CD0_total_boundary: float
    CD0_total_rescue: float
    CD_wing_profile_target: float
    CD_wing_profile_boundary: float
    CDA_nonwing_target_m2: float
    CDA_nonwing_boundary_m2: float
    CLmax_effective_assumption: float
    mission_contract_source: str
    source_mode: str = "shadow_no_ranking_gate"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_shadow_fields(self) -> dict[str, Any]:
        return {
            "mission_CL_req": float(self.CL_req),
            "mission_CD_wing_profile_target": float(self.CD_wing_profile_target),
            "mission_CD_wing_profile_boundary": float(self.CD_wing_profile_boundary),
            "mission_CDA_nonwing_target_m2": float(self.CDA_nonwing_target_m2),
            "mission_CDA_nonwing_boundary_m2": float(self.CDA_nonwing_boundary_m2),
            "mission_power_margin_required_w": float(self.power_margin_required_w),
            "mission_contract_source": str(self.mission_contract_source),
        }


def build_mission_contract(
    seed_row: Mapping[str, Any],
    screener_summary_or_config: Mapping[str, Any],
) -> MissionContract:
    """Build a mission contract from a seed row plus screener/config context."""

    speed_mps = _require_positive_float(
        _first_value(seed_row, ("speed_mps", "design_speed_mps")),
        "speed_mps",
    )
    span_m = _require_positive_float(_first_value(seed_row, ("span_m",)), "span_m")
    aspect_ratio = _require_positive_float(
        _first_value(seed_row, ("aspect_ratio", "AR")),
        "aspect_ratio",
    )
    wing_area_m2 = span_m**2 / aspect_ratio

    mass_kg = _require_positive_float(
        _first_numeric(
            seed_row,
            screener_summary_or_config,
            (
                ("mass_kg",),
                ("design_mass_kg",),
                ("max_mass_kg_robust",),
                ("min_mass_kg_robust",),
                ("search_bounds", "mass_kg", -1),
                ("suggested_main_design_region", "mass_kg", -1),
                ("observed_robust_envelope", "mass_kg", -1),
            ),
        ),
        "mass_kg",
    )
    weight_n = mass_kg * G_MPS2
    rho = _require_positive_float(
        _first_numeric(
            seed_row,
            screener_summary_or_config,
            (
                ("rho",),
                ("air_density_kg_m3",),
                ("density_kg_per_m3",),
                ("aircraft", "air_density_kg_m3", 0),
            ),
        ),
        "rho",
    )
    CL_req = weight_n / max(0.5 * rho * speed_mps**2 * wing_area_m2, 1.0e-12)

    target_range_km = _require_positive_float(
        _first_numeric(
            seed_row,
            screener_summary_or_config,
            (
                ("target_range_km",),
                ("mission_context", "target_range_km"),
                ("mission_reference", "target_range_km"),
                ("mission", "target_range_km"),
                ("mission", "target_distance_km"),
            ),
        ),
        "target_range_km",
    )
    required_time_min = target_range_km * 1000.0 / speed_mps / 60.0
    eta_prop = _require_positive_float(
        _first_numeric(
            seed_row,
            screener_summary_or_config,
            (
                ("eta_prop",),
                ("propulsion_budget", "eta_prop_target"),
                ("propulsion_budget", "eta_prop_sizing"),
                ("prop", "efficiency_model", "design_efficiency"),
            ),
            default=1.0,
        ),
        "eta_prop",
    )
    eta_trans = _require_positive_float(
        _first_numeric(
            seed_row,
            screener_summary_or_config,
            (
                ("eta_trans",),
                ("eta_transmission",),
                ("propulsion_budget", "eta_trans"),
                ("drivetrain", "efficiency"),
            ),
            default=1.0,
        ),
        "eta_trans",
    )
    pilot_power_hot_w = _optional_float(
        _first_numeric(
            seed_row,
            screener_summary_or_config,
            (
                ("pilot_power_hot_w",),
                ("available_power_w",),
                ("mission_context", "pilot_power_hot_w"),
            ),
        )
    )
    power_margin_required_w = _finite_float(
        _first_numeric(
            seed_row,
            screener_summary_or_config,
            (
                ("power_margin_required_w",),
                ("mission_gate", "robust_power_margin_crank_w_min"),
                ("mission_gate", "power_margin_crank_w_min"),
                ("robust_definition", "min_power_margin_crank_w"),
            ),
            default=0.0,
        ),
        "power_margin_required_w",
    )
    CD0_total_target = _finite_float(
        _first_numeric(
            seed_row,
            screener_summary_or_config,
            (
                ("CD0_total_target",),
                ("cd0_total_target",),
                ("total_drag_budget", "cd0_total_target"),
                ("search_bounds", "cd0_total", 0),
                ("suggested_main_design_region", "cd0_total", 0),
                ("cd0_total",),
            ),
        ),
        "CD0_total_target",
    )
    CD0_total_boundary = _finite_float(
        _first_numeric(
            seed_row,
            screener_summary_or_config,
            (
                ("CD0_total_boundary",),
                ("cd0_total_boundary",),
                ("total_drag_budget", "cd0_total_boundary"),
                ("search_bounds", "cd0_total", -1),
                ("suggested_main_design_region", "cd0_total", -1),
                ("cd0_total",),
            ),
            default=CD0_total_target,
        ),
        "CD0_total_boundary",
    )
    CD0_total_rescue = _finite_float(
        _first_numeric(
            seed_row,
            screener_summary_or_config,
            (
                ("CD0_total_rescue",),
                ("cd0_total_rescue",),
                ("total_drag_budget", "cd0_total_rescue"),
                ("observed_robust_envelope", "cd0_total", -1),
                ("cd0_total",),
            ),
            default=CD0_total_boundary,
        ),
        "CD0_total_rescue",
    )
    CDA_nonwing_target_m2 = _finite_float(
        _first_numeric(
            seed_row,
            screener_summary_or_config,
            (
                ("CDA_nonwing_target_m2",),
                ("cda_nonwing_target_m2",),
                ("nonwing_reserve", "cda_target_m2"),
                ("nonwing_reserve", "CDA_nonwing_target_m2"),
            ),
            default=0.0,
        ),
        "CDA_nonwing_target_m2",
    )
    CDA_nonwing_boundary_m2 = _finite_float(
        _first_numeric(
            seed_row,
            screener_summary_or_config,
            (
                ("CDA_nonwing_boundary_m2",),
                ("cda_nonwing_boundary_m2",),
                ("nonwing_reserve", "cda_boundary_m2"),
                ("nonwing_reserve", "CDA_nonwing_boundary_m2"),
            ),
            default=CDA_nonwing_target_m2,
        ),
        "CDA_nonwing_boundary_m2",
    )
    CLmax_effective_assumption = _require_positive_float(
        _first_numeric(
            seed_row,
            screener_summary_or_config,
            (
                ("CLmax_effective_assumption",),
                ("cl_max_effective",),
                ("max_clmax_effective_robust",),
                ("min_clmax_effective_robust",),
                ("search_bounds", "cl_max_effective", -1),
                ("suggested_main_design_region", "cl_max_effective", -1),
            ),
        ),
        "CLmax_effective_assumption",
    )

    return MissionContract(
        speed_mps=float(speed_mps),
        span_m=float(span_m),
        aspect_ratio=float(aspect_ratio),
        wing_area_m2=float(wing_area_m2),
        mass_kg=float(mass_kg),
        weight_n=float(weight_n),
        rho=float(rho),
        CL_req=float(CL_req),
        target_range_km=float(target_range_km),
        required_time_min=float(required_time_min),
        eta_prop=float(eta_prop),
        eta_trans=float(eta_trans),
        pilot_power_hot_w=pilot_power_hot_w,
        power_margin_required_w=float(power_margin_required_w),
        CD0_total_target=float(CD0_total_target),
        CD0_total_boundary=float(CD0_total_boundary),
        CD0_total_rescue=float(CD0_total_rescue),
        CD_wing_profile_target=float(CD0_total_target - CDA_nonwing_target_m2 / wing_area_m2),
        CD_wing_profile_boundary=float(
            CD0_total_boundary - CDA_nonwing_boundary_m2 / wing_area_m2
        ),
        CDA_nonwing_target_m2=float(CDA_nonwing_target_m2),
        CDA_nonwing_boundary_m2=float(CDA_nonwing_boundary_m2),
        CLmax_effective_assumption=float(CLmax_effective_assumption),
        mission_contract_source=str(
            screener_summary_or_config.get(
                "mission_contract_source",
                _source_label(screener_summary_or_config),
            )
        ),
    )


def _source_label(context: Mapping[str, Any]) -> str:
    schema = context.get("schema_version")
    if schema:
        return str(schema)
    if "optimizer_handoff" in context:
        return "mission_design_space_summary"
    if "total_drag_budget" in context:
        return "mission_drag_budget_config"
    return "unknown_mission_contract_context"


def _first_value(mapping: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def _first_numeric(
    seed_row: Mapping[str, Any],
    context: Mapping[str, Any],
    paths: tuple[tuple[Any, ...], ...],
    default: float | None = None,
) -> float | None:
    for path in paths:
        for mapping in (seed_row, context):
            value = _get_path(mapping, path)
            parsed = _optional_float(value)
            if parsed is not None:
                return parsed
    return default


def _get_path(mapping: Mapping[str, Any], path: tuple[Any, ...]) -> Any:
    value: Any = mapping
    for part in path:
        if isinstance(part, int):
            if not isinstance(value, (list, tuple)) or not value:
                return None
            try:
                value = value[part]
            except IndexError:
                return None
            continue
        if not isinstance(value, Mapping):
            return None
        value = value.get(str(part))
        if value is None:
            return None
    return value


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(parsed):
        return None
    return parsed


def _finite_float(value: Any, field_name: str) -> float:
    parsed = _optional_float(value)
    if parsed is None:
        raise ValueError(f"{field_name} must be finite.")
    return parsed


def _require_positive_float(value: Any, field_name: str) -> float:
    parsed = _finite_float(value, field_name)
    if parsed <= 0.0:
        raise ValueError(f"{field_name} must be > 0.")
    return parsed
