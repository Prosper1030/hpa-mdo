"""Shared AVL aero-gate contract helpers for outer-loop candidate screening."""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Protocol, Sequence

from hpa_mdo.aero.aswing_exporter import parse_avl
from hpa_mdo.core.config import HPAConfig


class TrimEvaluationLike(Protocol):
    """Protocol for trim outputs consumed by the aero-gate evaluator."""

    trim_converged: bool
    trim_status: str
    cl_trim: float | None
    cd_induced: float | None
    aoa_trim_deg: float | None
    span_efficiency: float | None


@dataclass(frozen=True)
class AeroPerformanceEvaluation:
    cl_trim: float | None
    cd_induced: float | None
    cd_total_est: float | None
    ld_ratio: float | None
    aoa_trim_deg: float | None
    span_efficiency: float | None
    lift_total_n: float | None
    aero_power_w: float | None
    aero_performance_feasible: bool
    aero_performance_reason: str


@dataclass(frozen=True)
class AvlAeroGateSettings:
    reference_area_source: str
    reference_area_m2: float
    reference_area_case_path: str
    air_density_kgpm3: float
    cruise_velocity_mps: float
    dynamic_pressure_pa: float
    trim_target_weight_kg: float
    trim_target_weight_n: float
    cl_required: float
    min_lift_kg: float
    min_lift_n: float
    min_ld_ratio: float
    cd_profile_estimate: float
    max_trim_aoa_deg: float
    soft_trim_aoa_deg: float
    stall_alpha_deg: float
    min_stall_margin_deg: float

    def to_metadata(
        self,
        *,
        skip_aero_gates: bool,
        skip_beta_sweep: bool,
        max_sideslip_deg: float,
        min_spiral_time_to_double_s: float,
        beta_sweep_values_deg: Sequence[float],
    ) -> dict[str, object]:
        return {
            "reference_area_source": str(self.reference_area_source),
            "reference_area_m2": float(self.reference_area_m2),
            "reference_area_case_path": str(self.reference_area_case_path),
            "air_density_kgpm3": float(self.air_density_kgpm3),
            "cruise_velocity_mps": float(self.cruise_velocity_mps),
            "dynamic_pressure_pa": float(self.dynamic_pressure_pa),
            "trim_target_weight_kg": float(self.trim_target_weight_kg),
            "trim_target_weight_n": float(self.trim_target_weight_n),
            "cl_required": float(self.cl_required),
            "min_lift_kg": float(self.min_lift_kg),
            "min_lift_n": float(self.min_lift_n),
            "min_ld_ratio": float(self.min_ld_ratio),
            "cd_profile_estimate": float(self.cd_profile_estimate),
            "max_trim_aoa_deg": float(self.max_trim_aoa_deg),
            "soft_trim_aoa_deg": float(self.soft_trim_aoa_deg),
            "stall_alpha_deg": float(self.stall_alpha_deg),
            "min_stall_margin_deg": float(self.min_stall_margin_deg),
            "skip_aero_gates": bool(skip_aero_gates),
            "skip_beta_sweep": bool(skip_beta_sweep),
            "max_sideslip_deg": float(max_sideslip_deg),
            "min_spiral_time_to_double_s": float(min_spiral_time_to_double_s),
            "beta_sweep_values_deg": [float(value) for value in beta_sweep_values_deg],
        }


def empty_aero_performance(*, feasible: bool, reason: str) -> AeroPerformanceEvaluation:
    return AeroPerformanceEvaluation(
        cl_trim=None,
        cd_induced=None,
        cd_total_est=None,
        ld_ratio=None,
        aoa_trim_deg=None,
        span_efficiency=None,
        lift_total_n=None,
        aero_power_w=None,
        aero_performance_feasible=bool(feasible),
        aero_performance_reason=str(reason),
    )


def load_reference_area_from_avl(case_avl_path: str | Path) -> float:
    """Return the reference area declared by the candidate AVL geometry."""

    avl_path = Path(case_avl_path).expanduser().resolve()
    area_m2 = float(parse_avl(avl_path).sref)
    if area_m2 <= 0.0:
        raise ValueError(
            f"Candidate AVL reference area must be positive: {avl_path}"
        )
    return area_m2


def build_avl_aero_gate_settings(
    *,
    cfg: HPAConfig,
    case_avl_path: str | Path,
    reference_area_source: str = "generated_avl_sref",
    min_lift_kg: float | None = None,
    min_ld_ratio: float | None = None,
    cd_profile_estimate: float | None = None,
    max_trim_aoa_deg: float | None = None,
    soft_trim_aoa_deg: float | None = None,
    stall_alpha_deg: float | None = None,
    min_stall_margin_deg: float | None = None,
) -> AvlAeroGateSettings:
    """Build the single-source-of-truth AVL aero gate contract for one candidate."""

    reference_area_m2 = load_reference_area_from_avl(case_avl_path)
    air_density_kgpm3 = float(cfg.flight.air_density)
    cruise_velocity_mps = float(cfg.flight.velocity)
    dynamic_pressure_pa = 0.5 * air_density_kgpm3 * cruise_velocity_mps**2
    if dynamic_pressure_pa <= 0.0:
        raise ValueError("Dynamic pressure must be positive for aero-gate trim analysis.")

    trim_target_weight_kg = float(cfg.weight.max_takeoff_kg)
    trim_target_weight_n = trim_target_weight_kg * 9.81
    cl_required = trim_target_weight_n / (dynamic_pressure_pa * reference_area_m2)

    return AvlAeroGateSettings(
        reference_area_source=str(reference_area_source),
        reference_area_m2=float(reference_area_m2),
        reference_area_case_path=str(Path(case_avl_path).expanduser().resolve()),
        air_density_kgpm3=float(air_density_kgpm3),
        cruise_velocity_mps=float(cruise_velocity_mps),
        dynamic_pressure_pa=float(dynamic_pressure_pa),
        trim_target_weight_kg=float(trim_target_weight_kg),
        trim_target_weight_n=float(trim_target_weight_n),
        cl_required=float(cl_required),
        min_lift_kg=(
            float(cfg.aero_gates.min_lift_kg)
            if min_lift_kg is None
            else float(min_lift_kg)
        ),
        min_lift_n=(
            float(cfg.aero_gates.min_lift_kg)
            if min_lift_kg is None
            else float(min_lift_kg)
        )
        * 9.81,
        min_ld_ratio=(
            float(cfg.aero_gates.min_ld_ratio)
            if min_ld_ratio is None
            else float(min_ld_ratio)
        ),
        cd_profile_estimate=(
            float(cfg.aero_gates.cd_profile_estimate)
            if cd_profile_estimate is None
            else float(cd_profile_estimate)
        ),
        max_trim_aoa_deg=(
            float(cfg.aero_gates.max_trim_aoa_deg)
            if max_trim_aoa_deg is None
            else float(max_trim_aoa_deg)
        ),
        soft_trim_aoa_deg=(
            float(cfg.aero_gates.soft_trim_aoa_deg)
            if soft_trim_aoa_deg is None
            else float(soft_trim_aoa_deg)
        ),
        stall_alpha_deg=(
            float(cfg.aero_gates.stall_alpha_deg)
            if stall_alpha_deg is None
            else float(stall_alpha_deg)
        ),
        min_stall_margin_deg=(
            float(cfg.aero_gates.min_stall_margin_deg)
            if min_stall_margin_deg is None
            else float(min_stall_margin_deg)
        ),
    )


def evaluate_aero_performance(
    *,
    trim_eval: TrimEvaluationLike,
    gate_settings: AvlAeroGateSettings,
) -> AeroPerformanceEvaluation:
    """Evaluate AVL trim results against the candidate's aero-gate contract."""

    if not trim_eval.trim_converged:
        return empty_aero_performance(feasible=False, reason=trim_eval.trim_status)

    cl_trim = trim_eval.cl_trim
    cd_induced = trim_eval.cd_induced
    aoa_trim_deg = trim_eval.aoa_trim_deg
    span_efficiency = trim_eval.span_efficiency
    if cl_trim is None or cd_induced is None or aoa_trim_deg is None:
        return empty_aero_performance(feasible=False, reason="trim_output_incomplete")

    cd_total_est = float(cd_induced) + float(gate_settings.cd_profile_estimate)
    if cd_total_est <= 0.0:
        return AeroPerformanceEvaluation(
            cl_trim=float(cl_trim),
            cd_induced=float(cd_induced),
            cd_total_est=float(cd_total_est),
            ld_ratio=None,
            aoa_trim_deg=float(aoa_trim_deg),
            span_efficiency=None if span_efficiency is None else float(span_efficiency),
            lift_total_n=None,
            aero_power_w=None,
            aero_performance_feasible=False,
            aero_performance_reason="nonpositive_drag_estimate",
        )

    ld_ratio = float(cl_trim) / float(cd_total_est)
    lift_total_n = (
        float(cl_trim)
        * float(gate_settings.dynamic_pressure_pa)
        * float(gate_settings.reference_area_m2)
    )
    aero_power_w = None
    if ld_ratio > 0.0:
        aero_power_w = (
            float(lift_total_n)
            * float(gate_settings.cruise_velocity_mps)
            / float(ld_ratio)
        )

    feasible = True
    reason = "ok"
    if float(aoa_trim_deg) > float(gate_settings.max_trim_aoa_deg):
        feasible = False
        reason = "trim_aoa_exceeds_limit"
    elif float(ld_ratio) < float(gate_settings.min_ld_ratio):
        feasible = False
        reason = "ld_below_minimum"
    elif not math.isclose(
        float(lift_total_n),
        float(gate_settings.min_lift_n),
        rel_tol=1.0e-6,
        abs_tol=1.0e-6,
    ) and float(lift_total_n) < float(gate_settings.min_lift_n):
        feasible = False
        reason = "insufficient_lift"

    return AeroPerformanceEvaluation(
        cl_trim=float(cl_trim),
        cd_induced=float(cd_induced),
        cd_total_est=float(cd_total_est),
        ld_ratio=float(ld_ratio),
        aoa_trim_deg=float(aoa_trim_deg),
        span_efficiency=None if span_efficiency is None else float(span_efficiency),
        lift_total_n=float(lift_total_n),
        aero_power_w=None if aero_power_w is None else float(aero_power_w),
        aero_performance_feasible=bool(feasible),
        aero_performance_reason=str(reason),
    )


__all__ = [
    "AeroPerformanceEvaluation",
    "AvlAeroGateSettings",
    "build_avl_aero_gate_settings",
    "empty_aero_performance",
    "evaluate_aero_performance",
    "load_reference_area_from_avl",
]
