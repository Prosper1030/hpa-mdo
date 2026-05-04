"""Cruise-aware no-airfoil twist oracle for MIT-like Birdman candidates.

The closed-loop driver in
``scripts/birdman_mit_like_closed_loop_search.py`` ran each MIT-like
candidate through AVL with a fixed monotone-washout schedule and
produced ``e_CDi(post-airfoil) = 0.71-0.80``.  The chief engineer then
asked for a **fixed-planform cruise-aware twist oracle**: keep the
MIT-like AR 37-40 / taper 0.30-0.40 planform untouched, **forbid any
outer chord bump**, and let a low-order twist parameterisation freely
search at the cruise CL_required to find the upper bound on the
no-airfoil e_CDi.

Twist parameterisation (4 DOF; matches the brief verbatim):

* ``root_incidence_deg`` — sets the whole-wing alpha at cruise (the
  knob that AVL's trim alpha would otherwise absorb).
* ``linear_washout_deg`` — total washout from root to tip applied
  linearly in eta.  Negative = washout (tip lower than root).
* ``outer_bump_amp_deg`` — additive smooth cosine bump centred at
  ``eta = 0.85`` (re-uses
  :func:`hpa_mdo.concept.outer_loading.outer_smooth_bump`).  Lets the
  oracle redistribute outer Ainc independently of the linear schedule.
* ``tip_correction_deg`` — additional cubic ``eta**3`` washout that
  bends the very tip without disturbing the inner schedule.

Objective at cruise (CL = m·g / (q·S)):

* primary: minimise AVL ``trim_cd_induced``,
* outer-loading penalty: ``max(0, target - actual)`` on the
  ``outer_min[0.80-0.92]`` ratio,
* target-match penalty: weighted RMS of the per-station
  ``cl_target_actual_norm - cl_target_target_norm`` deviation,
* smoothness penalty: low-order parameterisation already enforces
  smoothness; the penalty is on raw amplitudes to keep them sane.

Hard gates: candidate is **rejected** when

* twist physical gates fail
  (``hpa_mdo.concept`` smoke's ``_twist_gate_metrics``),
* tip gates fail (``_tip_gate_summary``),
* local CL utilisation exceeds the configured ceiling
  (``cfg.geometry_family.spanload_design.local_clmax_utilization_max``),
* AVL trim cannot converge.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from scipy.optimize import minimize

from hpa_mdo.aero.avl_spanwise import build_spanwise_load_from_avl_strip_forces
from hpa_mdo.concept.atmosphere import air_properties_from_environment
from hpa_mdo.concept.avl_loader import (
    _run_avl_spanwise_case,
    _run_avl_trim_case,
    resample_spanwise_load_to_stations,
    write_concept_wing_only_avl,
)
from hpa_mdo.concept.config import BirdmanConceptConfig
from hpa_mdo.concept.geometry import GeometryConcept, WingStation
from hpa_mdo.concept.outer_loading import outer_smooth_bump


G_MPS2: float = 9.80665


# Twist DOF bounds (4-DOF parameterisation).
TWIST_BOUNDS_DEG: dict[str, tuple[float, float]] = {
    "root_incidence_deg": (-1.0, 4.5),
    "linear_washout_deg": (-6.0, 0.0),
    "outer_bump_amp_deg": (-1.5, 2.5),
    "tip_correction_deg": (-2.0, 1.0),
}

OUTER_RATIO_TARGET_FLOOR: float = 0.85
OUTER_RATIO_ETA_WINDOW: tuple[float, float] = (0.80, 0.92)
TIP_TWIST_HARD_CAP_DEG: float = 6.0


@dataclass(frozen=True)
class TwistVector:
    """Container for the 4-DOF twist parameterisation."""

    root_incidence_deg: float
    linear_washout_deg: float
    outer_bump_amp_deg: float
    tip_correction_deg: float

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (
            float(self.root_incidence_deg),
            float(self.linear_washout_deg),
            float(self.outer_bump_amp_deg),
            float(self.tip_correction_deg),
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "root_incidence_deg": float(self.root_incidence_deg),
            "linear_washout_deg": float(self.linear_washout_deg),
            "outer_bump_amp_deg": float(self.outer_bump_amp_deg),
            "tip_correction_deg": float(self.tip_correction_deg),
        }


def twist_at_eta(twist: TwistVector, eta: float) -> float:
    """Evaluate the 4-DOF twist function at a single eta in [0, 1]."""

    eta_clamped = float(min(max(float(eta), 0.0), 1.0))
    return float(
        float(twist.root_incidence_deg)
        + float(twist.linear_washout_deg) * eta_clamped
        + float(twist.outer_bump_amp_deg) * outer_smooth_bump(eta_clamped)
        + float(twist.tip_correction_deg) * eta_clamped**3
    )


def apply_twist_to_stations(
    stations: tuple[WingStation, ...],
    twist: TwistVector,
) -> tuple[WingStation, ...]:
    """Replace ``station.twist_deg`` with the 4-DOF twist evaluation.

    The chord and dihedral schedules are left untouched (the planform
    is fixed; the oracle only tunes incidence)."""

    if not stations:
        return stations
    half_span = max(float(stations[-1].y_m), 1.0e-9)
    return tuple(
        WingStation(
            y_m=float(station.y_m),
            chord_m=float(station.chord_m),
            twist_deg=twist_at_eta(twist, float(station.y_m) / half_span),
            dihedral_deg=float(station.dihedral_deg),
        )
        for station in stations
    )


def _vector_from_array(values: np.ndarray) -> TwistVector:
    return TwistVector(
        root_incidence_deg=float(values[0]),
        linear_washout_deg=float(values[1]),
        outer_bump_amp_deg=float(values[2]),
        tip_correction_deg=float(values[3]),
    )


def _twist_smoothness_penalty(twist: TwistVector) -> float:
    """Soft penalty on twist amplitudes — keeps the optimiser away from
    pathological high-amplitude solutions when AVL is not enough to
    self-regulate."""

    return float(
        0.05 * twist.root_incidence_deg**2
        + 0.005 * twist.linear_washout_deg**2
        + 0.10 * twist.outer_bump_amp_deg**2
        + 0.10 * twist.tip_correction_deg**2
    )


def _twist_distribution(
    *,
    stations: tuple[WingStation, ...],
    twist: TwistVector,
) -> dict[str, Any]:
    twists_deg = [twist_at_eta(twist, station.y_m / max(stations[-1].y_m, 1.0e-9))
                  for station in stations]
    twist_range_deg = max(twists_deg) - min(twists_deg)
    max_abs_deg = max(abs(value) for value in twists_deg)
    adjacent_jumps = [
        abs(right - left) for left, right in zip(twists_deg[:-1], twists_deg[1:])
    ]
    max_adjacent_jump_deg = max(adjacent_jumps, default=0.0)
    outer_pairs = [
        (station.y_m / max(stations[-1].y_m, 1.0e-9), value)
        for station, value in zip(stations, twists_deg)
        if (station.y_m / max(stations[-1].y_m, 1.0e-9)) >= 0.45
    ]
    outer_wash_in_steps = [
        right_value - left_value
        for (_, left_value), (_, right_value) in zip(outer_pairs[:-1], outer_pairs[1:])
        if right_value > left_value
    ]
    max_outer_wash_in_step_deg = max(outer_wash_in_steps, default=0.0)
    return {
        "stations_twist_deg": list(map(float, twists_deg)),
        "twist_range_deg": float(twist_range_deg),
        "max_abs_twist_deg": float(max_abs_deg),
        "max_adjacent_jump_deg": float(max_adjacent_jump_deg),
        "max_outer_wash_in_step_deg": float(max_outer_wash_in_step_deg),
    }


def _twist_physical_gate_failures(distribution: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if float(distribution["max_abs_twist_deg"]) > TIP_TWIST_HARD_CAP_DEG:
        failures.append("twist_max_abs_exceeded")
    if float(distribution["twist_range_deg"]) > 7.0:
        failures.append("twist_range_exceeded")
    if float(distribution["max_adjacent_jump_deg"]) > 2.0:
        failures.append("twist_adjacent_jump_exceeded")
    if float(distribution["max_outer_wash_in_step_deg"]) > 0.6:
        failures.append("outer_monotonic_washout_failed")
    return failures


@dataclass(frozen=True)
class CruiseAvlEvaluation:
    twist: TwistVector
    aoa_trim_deg: float
    cl_trim: float
    cl_required: float
    cd_induced: float
    e_cdi: float
    span_efficiency_avl: float | None
    spanwise_table: list[dict[str, float]]
    outer_ratio_min: float | None
    outer_ratio_mean: float | None
    target_match_rms_norm_delta: float
    target_match_max_norm_delta: float
    twist_distribution: dict[str, Any]
    twist_gate_failures: list[str]
    local_cl_max_utilization: float
    objective_components: dict[str, float]
    objective_value: float
    failure_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "twist": self.twist.to_dict(),
            "aoa_trim_deg": float(self.aoa_trim_deg),
            "cl_trim": float(self.cl_trim),
            "cl_required": float(self.cl_required),
            "cd_induced": float(self.cd_induced),
            "e_cdi": float(self.e_cdi),
            "span_efficiency_avl": (
                None if self.span_efficiency_avl is None else float(self.span_efficiency_avl)
            ),
            "spanwise_table": list(self.spanwise_table),
            "outer_ratio_min": self.outer_ratio_min,
            "outer_ratio_mean": self.outer_ratio_mean,
            "target_match_rms_norm_delta": float(self.target_match_rms_norm_delta),
            "target_match_max_norm_delta": float(self.target_match_max_norm_delta),
            "twist_distribution": self.twist_distribution,
            "twist_gate_failures": list(self.twist_gate_failures),
            "local_cl_max_utilization": float(self.local_cl_max_utilization),
            "objective_components": self.objective_components,
            "objective_value": float(self.objective_value),
            "failure_reason": self.failure_reason,
        }


def _outer_ratio_metrics(
    spanwise_table: list[dict[str, float]],
    eta_window: tuple[float, float],
) -> tuple[float | None, float | None]:
    eta_lo, eta_hi = eta_window
    ratios: list[float] = []
    for row in spanwise_table:
        eta = float(row.get("eta", 0.0))
        ratio = row.get("avl_to_target_circulation_ratio")
        if ratio is None:
            continue
        if (eta_lo - 1.0e-4) <= eta <= (eta_hi + 1.0e-4):
            ratios.append(float(ratio))
    if not ratios:
        return None, None
    return float(min(ratios)), float(sum(ratios) / len(ratios))


def _target_match_norm_delta(spanwise_table: list[dict[str, float]]) -> tuple[float, float]:
    deltas = []
    for row in spanwise_table:
        target = row.get("target_circulation_norm")
        actual = row.get("avl_circulation_norm")
        if target is None or actual is None:
            continue
        deltas.append(float(actual) - float(target))
    if not deltas:
        return 0.0, 0.0
    rms = math.sqrt(sum(value**2 for value in deltas) / len(deltas))
    max_abs = max(abs(value) for value in deltas)
    return float(rms), float(max_abs)


def _build_spanwise_table(
    *,
    target_records: list[dict[str, Any]],
    avl_strip_points: list[dict[str, Any]],
    half_span_m: float,
) -> list[dict[str, Any]]:
    """Pair the inverse-chord target records with the AVL strip output.

    ``target_records`` come from the MIT-like target spanload (Fourier
    shape sized to the cruise CL); each row carries ``y_m``,
    ``chord_m``, ``target_local_cl``, and ``target_circulation_norm``.
    ``avl_strip_points`` are the ``cl_target`` points produced by
    ``avl_zone_payload_from_spanwise_load`` — we re-normalise them by
    ``max(cl_target * chord_m)`` to get a comparable ``avl_circulation_norm``.
    """

    if not avl_strip_points:
        return [
            {
                **record,
                "avl_local_cl": None,
                "avl_circulation_norm": None,
                "avl_to_target_circulation_ratio": None,
            }
            for record in target_records
        ]
    avl_max_circulation = max(
        float(point.get("cl_target", 0.0)) * float(point.get("chord_m", 0.0))
        for point in avl_strip_points
    ) or 1.0
    out: list[dict[str, Any]] = []
    for record in target_records:
        nearest = min(
            avl_strip_points,
            key=lambda point: abs(
                float(point.get("station_y_m", 0.0)) - float(record["y_m"])
            ),
        )
        avl_local_cl = float(nearest.get("cl_target", 0.0))
        avl_circulation = avl_local_cl * float(nearest.get("chord_m", 0.0))
        avl_norm = avl_circulation / avl_max_circulation
        target_norm = float(record.get("target_circulation_norm", 0.0))
        ratio = (
            float(avl_norm / target_norm)
            if abs(target_norm) > 1.0e-9
            else None
        )
        out.append(
            {
                "eta": float(record.get("eta", 0.0)),
                "y_m": float(record["y_m"]),
                "chord_m": float(record["chord_m"]),
                "target_local_cl": float(record.get("target_local_cl", 0.0)),
                "target_circulation_norm": float(target_norm),
                "avl_local_cl": float(avl_local_cl),
                "avl_circulation_norm": float(avl_norm),
                "avl_to_target_circulation_ratio": ratio,
                "reynolds": float(record.get("reynolds", 0.0)),
            }
        )
    return out


def _evaluate_twist(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    base_stations: tuple[WingStation, ...],
    twist: TwistVector,
    cruise_speed_mps: float,
    cl_required: float,
    target_records: list[dict[str, Any]],
    target_clmax_safe_floor: float,
    target_clmax_utilization_max: float,
    avl_binary: str | None,
    case_dir: Path,
    weights: dict[str, float],
) -> CruiseAvlEvaluation:
    stations = apply_twist_to_stations(base_stations, twist)
    distribution = _twist_distribution(stations=stations, twist=twist)
    twist_failures = _twist_physical_gate_failures(distribution)

    air = air_properties_from_environment(
        temperature_c=float(cfg.environment.temperature_c),
        relative_humidity_percent=float(cfg.environment.relative_humidity),
        altitude_m=float(cfg.environment.altitude_m),
    )
    avl_path = case_dir / "concept_wing.avl"
    write_concept_wing_only_avl(
        concept=concept,
        stations=stations,
        output_path=avl_path,
        zone_airfoil_paths=None,
    )
    avl_case_dir = case_dir / "cruise_no_airfoil"
    failure_reason: str | None = None
    aoa_trim_deg = float("nan")
    cl_trim = float("nan")
    cd_induced = float("nan")
    span_efficiency = None
    spanwise_table = [
        {
            **record,
            "avl_local_cl": None,
            "avl_circulation_norm": None,
            "avl_to_target_circulation_ratio": None,
        }
        for record in target_records
    ]
    try:
        trim_totals = _run_avl_trim_case(
            avl_path=avl_path,
            case_dir=avl_case_dir,
            cl_required=float(cl_required),
            velocity_mps=float(cruise_speed_mps),
            density_kgpm3=float(air.density_kg_per_m3),
            avl_binary=avl_binary,
        )
        aoa_trim_deg = float(trim_totals.get("aoa_trim_deg", float("nan")))
        cl_trim = float(trim_totals.get("cl_trim", float("nan")))
        cd_induced = float(trim_totals.get("cd_induced", float("nan")))
        span_efficiency = trim_totals.get("span_efficiency")
        fs_path = _run_avl_spanwise_case(
            avl_path=avl_path,
            case_dir=avl_case_dir,
            alpha_deg=aoa_trim_deg,
            velocity_mps=float(cruise_speed_mps),
            density_kgpm3=float(air.density_kg_per_m3),
            avl_binary=avl_binary,
        )
        avl_spanwise_load = build_spanwise_load_from_avl_strip_forces(
            fs_path=fs_path,
            avl_path=avl_path,
            aoa_deg=aoa_trim_deg,
            velocity_mps=float(cruise_speed_mps),
            density_kgpm3=float(air.density_kg_per_m3),
            target_surface_names=("Wing",),
            positive_y_only=True,
        )
        station_load = resample_spanwise_load_to_stations(
            spanwise_load=avl_spanwise_load,
            stations=stations,
        )
        # ``station_load`` is a SpanwiseLoad with parallel numpy arrays.
        avl_strip_points = [
            {
                "station_y_m": float(y_value),
                "chord_m": float(chord_value),
                "cl_target": float(cl_value),
            }
            for y_value, chord_value, cl_value in zip(
                station_load.y, station_load.chord, station_load.cl
            )
        ]
        spanwise_table = _build_spanwise_table(
            target_records=target_records,
            avl_strip_points=avl_strip_points,
            half_span_m=0.5 * float(concept.span_m),
        )
    except Exception as exc:  # noqa: BLE001 - surface AVL failures into the result.
        failure_reason = f"avl_failed:{exc}"

    outer_ratio_min, outer_ratio_mean = _outer_ratio_metrics(
        spanwise_table, OUTER_RATIO_ETA_WINDOW
    )
    rms_delta, max_delta = _target_match_norm_delta(spanwise_table)
    e_cdi_value = (
        float(cl_trim) ** 2
        / max(math.pi * float(concept.aspect_ratio) * float(cd_induced), 1.0e-9)
        if math.isfinite(cd_induced) and cd_induced > 0.0 and math.isfinite(cl_trim)
        else 0.0
    )

    local_cl_max_utilization = max(
        (
            float(row.get("avl_local_cl", 0.0)) / max(float(target_clmax_safe_floor), 1.0e-9)
            for row in spanwise_table
            if row.get("avl_local_cl") is not None
        ),
        default=0.0,
    )

    objective_components = {
        "cd_induced": float(weights["cd_induced"]) * float(cd_induced if math.isfinite(cd_induced) else 1.0),
        "outer_ratio_penalty": float(weights["outer_ratio"]) * (
            max(0.0, OUTER_RATIO_TARGET_FLOOR - float(outer_ratio_min))
            if outer_ratio_min is not None
            else 1.0
        )
        ** 2,
        "target_match_rms": float(weights["target_match"]) * float(rms_delta) ** 2,
        "smoothness": float(weights["smoothness"]) * _twist_smoothness_penalty(twist),
        "twist_gate_penalty": float(weights["twist_gate_penalty"]) * float(len(twist_failures)),
        "local_cl_penalty": float(weights["local_cl_penalty"]) * (
            max(
                0.0,
                float(local_cl_max_utilization) - float(target_clmax_utilization_max),
            )
            ** 2
        ),
    }
    if failure_reason is not None:
        objective_components["avl_failed"] = 1.0e6

    objective_value = float(sum(objective_components.values()))

    return CruiseAvlEvaluation(
        twist=twist,
        aoa_trim_deg=aoa_trim_deg,
        cl_trim=cl_trim,
        cl_required=float(cl_required),
        cd_induced=cd_induced,
        e_cdi=e_cdi_value,
        span_efficiency_avl=(
            None if span_efficiency is None else float(span_efficiency)
        ),
        spanwise_table=spanwise_table,
        outer_ratio_min=outer_ratio_min,
        outer_ratio_mean=outer_ratio_mean,
        target_match_rms_norm_delta=float(rms_delta),
        target_match_max_norm_delta=float(max_delta),
        twist_distribution=distribution,
        twist_gate_failures=twist_failures,
        local_cl_max_utilization=float(local_cl_max_utilization),
        objective_components=objective_components,
        objective_value=objective_value,
        failure_reason=failure_reason,
    )


def optimize_twist_for_candidate(
    *,
    cfg: BirdmanConceptConfig,
    concept: GeometryConcept,
    base_stations: tuple[WingStation, ...],
    target_records: list[dict[str, Any]],
    cruise_speed_mps: float,
    output_dir: Path,
    avl_binary: str | None,
    initial_twists: Iterable[TwistVector] | None = None,
    optimizer_maxfev: int = 30,
    optimizer_maxiter: int = 6,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Run the 4-DOF twist oracle for a single candidate.

    The oracle evaluates a small seed bank of TwistVectors first
    (controlled twist guesses + zero), then runs scipy Powell from the
    best seed.  Returns the best-of-evaluations record and the full
    evaluation log so the caller can audit the path.
    """

    output_dir.mkdir(parents=True, exist_ok=True)
    bounds = list(TWIST_BOUNDS_DEG.values())
    weights = weights or {
        "cd_induced": 200.0,
        "outer_ratio": 30.0,
        "target_match": 8.0,
        "smoothness": 0.2,
        "twist_gate_penalty": 5.0,
        "local_cl_penalty": 50.0,
    }

    spanload_design = cfg.geometry_family.spanload_design
    safe_clmax = float(spanload_design.local_clmax_safe_floor)
    util_max = float(spanload_design.local_clmax_utilization_max)

    air = air_properties_from_environment(
        temperature_c=float(cfg.environment.temperature_c),
        relative_humidity_percent=float(cfg.environment.relative_humidity),
        altitude_m=float(cfg.environment.altitude_m),
    )
    q_pa = 0.5 * float(air.density_kg_per_m3) * float(cruise_speed_mps) ** 2
    cl_required = float(
        float(cfg.mass.design_gross_mass_kg)
        * float(G_MPS2)
        / max(q_pa * float(concept.wing_area_m2), 1.0e-9)
    )

    if initial_twists is None:
        initial_twists = (
            TwistVector(2.0, -3.0, 0.0, 0.0),
            TwistVector(2.5, -4.0, 0.5, -0.5),
            TwistVector(3.0, -4.5, 1.0, -1.0),
            TwistVector(2.0, -2.0, 0.0, 0.0),
            TwistVector(1.5, -3.5, 1.0, -0.5),
        )

    evaluation_log: list[dict[str, Any]] = []
    eval_counter = [0]

    def _eval(twist_vector: TwistVector) -> CruiseAvlEvaluation:
        eval_counter[0] += 1
        case_dir = output_dir / f"eval_{eval_counter[0]:03d}"
        result = _evaluate_twist(
            cfg=cfg,
            concept=concept,
            base_stations=base_stations,
            twist=twist_vector,
            cruise_speed_mps=cruise_speed_mps,
            cl_required=cl_required,
            target_records=target_records,
            target_clmax_safe_floor=safe_clmax,
            target_clmax_utilization_max=util_max,
            avl_binary=avl_binary,
            case_dir=case_dir,
            weights=weights,
        )
        evaluation_log.append(result.to_dict())
        return result

    best = None
    for seed in initial_twists:
        result = _eval(seed)
        if best is None or result.objective_value < best.objective_value:
            best = result
    if best is None:  # defensive — initial_twists should never be empty.
        return {"status": "no_initial_twists", "evaluations": evaluation_log}

    def objective(values: np.ndarray) -> float:
        twist_vector = _vector_from_array(values)
        return _eval(twist_vector).objective_value

    if optimizer_maxfev > 0 and optimizer_maxiter > 0:
        x0 = np.asarray(best.twist.as_tuple(), dtype=float)
        try:
            minimize(
                objective,
                x0,
                method="Powell",
                bounds=bounds,
                options={
                    "maxfev": int(optimizer_maxfev),
                    "maxiter": int(optimizer_maxiter),
                    "xtol": 0.05,
                    "ftol": 1.0e-3,
                    "disp": False,
                },
            )
        except Exception as exc:  # noqa: BLE001 - keep the seed-best on optimizer crash.
            evaluation_log.append({"optimizer_error": str(exc)})

    # Choose the genuine best across all evaluations.
    valid = [
        entry
        for entry in evaluation_log
        if isinstance(entry, dict)
        and "objective_value" in entry
        and entry.get("failure_reason") is None
    ]
    if not valid:
        return {
            "status": "all_evaluations_failed",
            "evaluations": evaluation_log,
            "cl_required": cl_required,
        }
    best_entry = min(valid, key=lambda entry: float(entry["objective_value"]))
    return {
        "status": "ok",
        "cl_required": float(cl_required),
        "evaluations": evaluation_log,
        "best": best_entry,
    }
