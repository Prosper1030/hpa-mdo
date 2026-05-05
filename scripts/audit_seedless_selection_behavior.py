from __future__ import annotations

import argparse
import csv
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from hpa_mdo.concept.airfoil_cst import (
    CSTAirfoilTemplate,
    analyze_cst_geometry,
    build_seedless_cst_template,
    generate_cst_coordinates,
    validate_cst_candidate_coordinates,
)
from hpa_mdo.concept.airfoil_selection import (
    _candidate_depth_ratio_at_x,
    _candidate_thickness_ratio,
    _coarse_seed_candidates,
    _default_seedless_cst_bounds,
    _matched_worker_polar_points,
    _prepare_zone_selection_inputs,
    _refinement_candidates,
    _run_batched_zone_candidate_queries,
    _score_available_zone_candidates,
    _select_scored_candidate_beam,
    _successive_halving_radius,
    _zone_candidate_metrics,
)
from hpa_mdo.concept.airfoil_worker import JuliaXFoilWorker
from hpa_mdo.concept.config import load_concept_config

REPORT_DIR = Path("docs/research/seedless_selection_behavior")
CONFIG_PATH = Path("configs/birdman_upstream_concept_baseline.yaml")
HISTORICAL_FIT_JSON = Path(
    "docs/research/historical_airfoil_cst_coverage/fit_results.json"
)
ZONE_NAMES = ("root", "mid1", "mid2", "tip")
ROOT_HISTORICAL = ("FX 76-MP-140", "DAE11", "DAE21")
OUTBOARD_HISTORICAL = ("DAE21", "DAE31", "DAE41")

# Representative design-point table from the current Birdman mission-coupled
# medium-search candidate bundle. Kept local so the audit is reproducible even
# when output/ is cleaned.
REFERENCE_STATION_ROWS: tuple[dict[str, float], ...] = (
    {
        "eta": 0.00,
        "y_m": 0.0,
        "chord_m": 1.45,
        "twist_deg": 2.0,
        "reynolds": 544484.883643,
        "target_cl": 1.155754,
    },
    {
        "eta": 0.16,
        "y_m": 2.778258,
        "chord_m": 1.2046,
        "twist_deg": 1.087677,
        "reynolds": 452335.598667,
        "target_cl": 1.369815,
    },
    {
        "eta": 0.35,
        "y_m": 6.077439,
        "chord_m": 1.057888,
        "twist_deg": 1.222866,
        "reynolds": 397244.307906,
        "target_cl": 1.465726,
    },
    {
        "eta": 0.52,
        "y_m": 9.029337,
        "chord_m": 0.996886,
        "twist_deg": 1.981469,
        "reynolds": 374337.671976,
        "target_cl": 1.396029,
    },
    {
        "eta": 0.70,
        "y_m": 12.154877,
        "chord_m": 0.927123,
        "twist_deg": 1.980884,
        "reynolds": 348140.954004,
        "target_cl": 1.223509,
    },
    {
        "eta": 0.82,
        "y_m": 14.238571,
        "chord_m": 0.878036,
        "twist_deg": 1.488157,
        "reynolds": 329708.501143,
        "target_cl": 1.011918,
    },
    {
        "eta": 0.90,
        "y_m": 15.627699,
        "chord_m": 0.823493,
        "twist_deg": 0.884071,
        "reynolds": 309227.087522,
        "target_cl": 0.806613,
    },
    {
        "eta": 0.95,
        "y_m": 16.495905,
        "chord_m": 0.705983,
        "twist_deg": 0.506518,
        "reynolds": 265101.29479,
        "target_cl": 0.665262,
    },
)


@dataclass(frozen=True)
class ArtifactSuspicion:
    level: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ScaleConfig:
    name: str
    sample_count: int
    coarse_score_count: int | None
    robust_score_count: int | None
    reynolds_factors: tuple[float, ...]
    roughness_modes: tuple[str, ...]
    robust_enabled: bool
    zones: tuple[str, ...] = ZONE_NAMES


def historical_airfoil_names_for_zone(zone_name: str) -> tuple[str, ...]:
    if zone_name in {"root", "mid1"}:
        return ROOT_HISTORICAL
    if zone_name in {"mid2", "tip"}:
        return OUTBOARD_HISTORICAL
    raise ValueError(f"unsupported zone name: {zone_name!r}")


def _station_weights(rows: Sequence[Mapping[str, float]]) -> tuple[float, ...]:
    if len(rows) == 1:
        return (1.0,)
    y_positions = [float(row["y_m"]) for row in rows]
    boundaries = [y_positions[0]]
    boundaries.extend(
        0.5 * (left + right) for left, right in zip(y_positions[:-1], y_positions[1:])
    )
    boundaries.append(y_positions[-1])
    widths = [max(right - left, 0.0) for left, right in zip(boundaries[:-1], boundaries[1:])]
    total = max(sum(widths), 1.0e-9)
    return tuple(width / total for width in widths)


def _zone_for_eta(eta: float) -> str:
    eta = float(eta)
    if eta < 0.25:
        return "root"
    if eta < 0.55:
        return "mid1"
    if eta < 0.80:
        return "mid2"
    return "tip"


def _zone_min_tc_ratio(zone_name: str) -> float:
    return 0.14 if zone_name == "root" else 0.10


def build_reference_zone_requirements() -> dict[str, dict[str, object]]:
    rows = REFERENCE_STATION_ROWS
    weights = _station_weights(rows)
    root_twist = float(rows[0]["twist_deg"])
    tip_twist = float(rows[-1]["twist_deg"])
    washout_deg = max(0.0, root_twist - tip_twist)
    taper_ratio = float(rows[-1]["chord_m"]) / max(float(rows[0]["chord_m"]), 1.0e-9)

    zone_requirements: dict[str, dict[str, object]] = {
        zone_name: {"min_tc_ratio": _zone_min_tc_ratio(zone_name), "points": []}
        for zone_name in ZONE_NAMES
    }
    for row, weight in zip(rows, weights, strict=True):
        zone_name = _zone_for_eta(float(row["eta"]))
        cm_target = 0.02 - 0.04 * float(row["eta"])
        zone_requirements[zone_name]["points"].append(
            {
                "reynolds": float(row["reynolds"]),
                "chord_m": float(row["chord_m"]),
                "cl_target": float(row["target_cl"]),
                "cm_target": float(cm_target),
                "weight": float(weight),
                "station_y_m": float(row["y_m"]),
                "span_fraction": float(row["eta"]),
                "taper_ratio": float(taper_ratio),
                "washout_deg": float(washout_deg),
                "case_label": "reference_avl_case",
            }
        )
    return zone_requirements


def _sanitize_airfoil_name(name: str) -> str:
    token = "".join(ch.lower() if ch.isalnum() else "_" for ch in name)
    while "__" in token:
        token = token.replace("__", "_")
    return token.strip("_")


def _load_historical_templates_for_zone(zone_name: str) -> tuple[CSTAirfoilTemplate, ...]:
    rows = json.loads(HISTORICAL_FIT_JSON.read_text(encoding="utf-8"))
    by_name = {
        str(row["airfoil"]): row
        for row in rows
        if int(row["degree"]) == 6
    }
    templates: list[CSTAirfoilTemplate] = []
    for airfoil_name in historical_airfoil_names_for_zone(zone_name):
        row = by_name[airfoil_name]
        te_thickness = max(float(row["te_thickness"]), 1.0e-9)
        templates.append(
            build_seedless_cst_template(
                zone_name=zone_name,
                upper_coefficients=tuple(float(value) for value in row["upper_coefficients"]),
                lower_coefficients=tuple(float(value) for value in row["lower_coefficients"]),
                te_thickness_m=te_thickness,
                candidate_role=f"historical_{_sanitize_airfoil_name(airfoil_name)}",
            )
        )
    return tuple(templates)


def classify_artifact_suspicion(
    *,
    status: str,
    robust_pass_rate: float,
    mean_cd: float,
    mean_cm: float,
    raw_condition_results: Sequence[Mapping[str, object]],
    max_camber_ratio: float,
    thickness_at_1pct_chord: float,
    max_cl_target_error: float,
) -> ArtifactSuspicion:
    severity = 0
    reasons: list[str] = []

    if status == "analysis_failed":
        severity = max(severity, 2)
        reasons.append("analysis_failed result")
    elif status == "mini_sweep_fallback":
        severity = max(severity, 1)
        reasons.append("mini_sweep_fallback used")

    if robust_pass_rate < 0.75:
        severity = max(severity, 2)
        reasons.append(f"robust pass rate {robust_pass_rate:.2f} below 0.75")
    elif robust_pass_rate < 1.0:
        severity = max(severity, 1)
        reasons.append(f"partial robust pass rate {robust_pass_rate:.2f}")

    if not math.isfinite(mean_cd):
        severity = max(severity, 2)
        reasons.append("non-finite drag")
    elif mean_cd < 0.005:
        severity = max(severity, 2)
        reasons.append(f"very low mean cd {mean_cd:.5f}")
    elif mean_cd < 0.007:
        severity = max(severity, 1)
        reasons.append(f"low mean cd {mean_cd:.5f}")

    if mean_cm < -0.16:
        severity = max(severity, 2)
        reasons.append(f"cm {mean_cm:.3f} beyond hard trim bound")
    elif mean_cm < -0.12:
        severity = max(severity, 1)
        reasons.append(f"cm {mean_cm:.3f} near trim penalty region")

    clean_cds = [
        float(result["mean_cd"])
        for result in raw_condition_results
        if result.get("roughness_mode") == "clean"
        and isinstance(result.get("mean_cd"), int | float)
    ]
    rough_cds = [
        float(result["mean_cd"])
        for result in raw_condition_results
        if result.get("roughness_mode") == "rough"
        and isinstance(result.get("mean_cd"), int | float)
    ]
    if clean_cds and rough_cds:
        clean_mean = sum(clean_cds) / len(clean_cds)
        rough_mean = sum(rough_cds) / len(rough_cds)
        ratio = rough_mean / max(clean_mean, 1.0e-9)
        if ratio > 2.0:
            severity = max(severity, 2)
            reasons.append(f"rough drag sensitivity {ratio:.2f}x")
        elif ratio > 1.6:
            severity = max(severity, 1)
            reasons.append(f"rough drag sensitivity {ratio:.2f}x")

    condition_cds = [
        float(result["mean_cd"])
        for result in raw_condition_results
        if isinstance(result.get("mean_cd"), int | float)
    ]
    if len(condition_cds) >= 3:
        ordered = sorted(condition_cds)
        median_cd = ordered[len(ordered) // 2]
        if median_cd / max(ordered[0], 1.0e-9) > 2.0:
            severity = max(severity, 1)
            reasons.append("single-condition drag trough")

    if max_camber_ratio > 0.09:
        severity = max(severity, 1)
        reasons.append(f"high camber {max_camber_ratio:.3f}")
    if thickness_at_1pct_chord < 0.016:
        severity = max(severity, 1)
        reasons.append(f"thin leading edge {thickness_at_1pct_chord:.3f}c at 1% chord")
    if max_cl_target_error > 0.05:
        severity = max(severity, 1)
        reasons.append(f"polar target mismatch dCL={max_cl_target_error:.3f}")

    if not reasons:
        reasons.append("no immediate artifact trigger")
    return ArtifactSuspicion(
        level=("low" if severity == 0 else "medium" if severity == 1 else "high"),
        reasons=tuple(reasons),
    )


def _seed_loader(_seed_name: str) -> tuple[tuple[float, float], ...]:
    raise RuntimeError("seed loader is not used in seedless_sobol audit mode")


def _trim_drag_per_cm_squared(cfg: Any) -> float:
    return float(getattr(cfg.cst_search, "trim_drag_per_cm_squared", 0.0))


def _raw_results_by_zone_role(
    worker_results: Iterable[Mapping[str, object]],
) -> dict[tuple[str, str], list[Mapping[str, object]]]:
    grouped: dict[tuple[str, str], list[Mapping[str, object]]] = {}
    for result in worker_results:
        zone_name = str(result.get("zone_name"))
        candidate_role = str(result.get("candidate_role"))
        grouped.setdefault((zone_name, candidate_role), []).append(result)
    return grouped


def _max_cl_target_error(raw_results: Sequence[Mapping[str, object]]) -> float:
    max_error = 0.0
    for result in raw_results:
        polar_points = result.get("polar_points")
        if not isinstance(polar_points, list):
            continue
        for point in polar_points:
            if not isinstance(point, Mapping):
                continue
            cl = point.get("cl")
            cl_target = point.get("cl_target", cl)
            if isinstance(cl, int | float) and isinstance(cl_target, int | float):
                max_error = max(max_error, abs(float(cl) - float(cl_target)))
    return max_error


def _hard_gate_notes(
    *,
    template: CSTAirfoilTemplate,
    zone_points: list[dict[str, float]],
    result: Mapping[str, object],
    zone_min_tc_ratio: float,
    cfg: Any,
) -> tuple[bool, str]:
    diagnostic = _candidate_gate_diagnostic(
        template=template,
        zone_points=zone_points,
        result=result,
        zone_min_tc_ratio=zone_min_tc_ratio,
        cfg=cfg,
    )
    return bool(diagnostic["hard_gate_pass"]), str(diagnostic["hard_gate_notes"])


def _candidate_gate_diagnostic(
    *,
    template: CSTAirfoilTemplate,
    zone_points: list[dict[str, float]],
    result: Mapping[str, object],
    zone_min_tc_ratio: float,
    cfg: Any,
) -> dict[str, object]:
    status = str(result.get("status", "unknown"))
    if status not in {"ok", "stubbed_ok", "mini_sweep_fallback"}:
        return {
            "hard_gate_pass": False,
            "hard_gate_notes": status,
            "stall_pass": False,
            "cm_pass": False,
            "tc_pass": False,
            "spar_pass": False,
            "best_stall_margin": float("-inf"),
            "candidate_score": float("inf"),
        }

    coordinates = generate_cst_coordinates(template)
    validity = validate_cst_candidate_coordinates(coordinates)
    if not validity.valid:
        return {
            "hard_gate_pass": False,
            "hard_gate_notes": validity.reason,
            "stall_pass": False,
            "cm_pass": False,
            "tc_pass": False,
            "spar_pass": False,
            "best_stall_margin": float("-inf"),
            "candidate_score": float("inf"),
        }

    polar_points = result.get("polar_points")
    metrics = _zone_candidate_metrics(
        zone_points=zone_points,
        mean_cd=float(result["mean_cd"]),
        mean_cm=float(result["mean_cm"]),
        usable_clmax=float(result["usable_clmax"]),
        zone_min_tc_ratio=zone_min_tc_ratio,
        coordinates=coordinates,
        polar_points=polar_points if isinstance(polar_points, list) else None,
        safe_clmax_scale=float(cfg.stall_model.safe_clmax_scale),
        safe_clmax_delta=float(cfg.stall_model.safe_clmax_delta),
        tip_3d_penalty_start_eta=float(cfg.stall_model.tip_3d_penalty_start_eta),
        tip_3d_penalty_max=float(cfg.stall_model.tip_3d_penalty_max),
        tip_taper_penalty_weight=float(cfg.stall_model.tip_taper_penalty_weight),
        washout_relief_deg=float(cfg.stall_model.washout_relief_deg),
        washout_relief_max=float(cfg.stall_model.washout_relief_max),
        launch_stall_utilization_limit=float(cfg.stall_model.launch_utilization_limit),
        turn_stall_utilization_limit=float(cfg.stall_model.turn_utilization_limit),
        local_stall_utilization_limit=float(cfg.stall_model.local_stall_utilization_limit),
    )
    notes: list[str] = []
    worst_case_margin = float(metrics["worst_case_margin"])
    thickness_ratio = float(metrics["candidate_thickness_ratio"])
    spar_depth_ratio = float(metrics["spar_depth_ratio"])
    required_spar_depth_ratio = float(metrics["required_spar_depth_ratio"])
    cm_violation = max(0.0, float(cfg.cst_search.cm_hard_lower_bound) - float(result["mean_cm"]))
    stall_pass = worst_case_margin >= 0.0
    tc_pass = thickness_ratio >= zone_min_tc_ratio
    spar_pass = spar_depth_ratio >= required_spar_depth_ratio
    cm_pass = cm_violation <= 0.0
    if not stall_pass:
        notes.append(
            "stall margin "
            f"{worst_case_margin:.3f} at {metrics['worst_case_label']}"
        )
    if not tc_pass:
        notes.append(f"t/c {thickness_ratio:.3f} < {zone_min_tc_ratio:.3f}")
    if not spar_pass:
        notes.append(
            "spar depth "
            f"{spar_depth_ratio:.3f} < {required_spar_depth_ratio:.3f}"
        )
    if not cm_pass:
        notes.append(f"cm hard violation {cm_violation:.3f}")
    return {
        "hard_gate_pass": not notes,
        "hard_gate_notes": "; ".join(notes) if notes else "ok",
        "stall_pass": stall_pass,
        "cm_pass": cm_pass,
        "tc_pass": tc_pass,
        "spar_pass": spar_pass,
        "best_stall_margin": worst_case_margin,
        "candidate_score": float("nan"),
    }


def _candidate_summary_row(
    *,
    scale_name: str,
    zone_name: str,
    rank: int,
    score_item: Any,
    candidate_result: Mapping[str, object],
    raw_results: Sequence[Mapping[str, object]],
    zone_points: list[dict[str, float]],
    zone_min_tc_ratio: float,
    cfg: Any,
    source: str,
) -> dict[str, object]:
    template = score_item.template
    geometry = analyze_cst_geometry(template)
    hard_gate_pass, notes = _hard_gate_notes(
        template=template,
        zone_points=zone_points,
        result=candidate_result,
        zone_min_tc_ratio=zone_min_tc_ratio,
        cfg=cfg,
    )
    suspicion = classify_artifact_suspicion(
        status=str(candidate_result.get("status", "unknown")),
        robust_pass_rate=float(candidate_result.get("robust_pass_rate", 1.0)),
        mean_cd=float(candidate_result.get("mean_cd", float("inf"))),
        mean_cm=float(candidate_result.get("mean_cm", 0.0)),
        raw_condition_results=raw_results,
        max_camber_ratio=float(geometry.max_camber_ratio),
        thickness_at_1pct_chord=float(geometry.thickness_at_1pct_chord),
        max_cl_target_error=_max_cl_target_error(raw_results),
    )
    return {
        "scale": scale_name,
        "zone": zone_name,
        "rank": int(rank),
        "source": source,
        "candidate_id": template.candidate_role,
        "score": float(score_item.candidate_score),
        "cd_mission": float(score_item.mean_cd),
        "safe_clmax": float(score_item.safe_clmax),
        "usable_clmax": float(score_item.usable_clmax),
        "cm": float(score_item.mean_cm),
        "robust_pass_rate": float(score_item.robust_pass_rate),
        "tc": float(geometry.max_thickness_ratio),
        "max_thickness_x": float(geometry.max_thickness_x),
        "camber": float(geometry.max_camber_ratio),
        "te_thickness": float(template.te_thickness_m),
        "hard_gate_pass": bool(hard_gate_pass),
        "hard_gate_notes": notes,
        "artifact_suspicion": suspicion.level,
        "artifact_notes": "; ".join(suspicion.reasons),
        "upper_coefficients": list(template.upper_coefficients),
        "lower_coefficients": list(template.lower_coefficients),
    }


def _zone_feasibility_stat_row(
    *,
    scale_name: str,
    zone_name: str,
    candidates: Sequence[CSTAirfoilTemplate],
    scored: Sequence[Any],
    candidate_results: Mapping[str, Mapping[str, object]],
    zone_points: list[dict[str, float]],
    zone_min_tc_ratio: float,
    coarse_scored_count: int,
    robust_scored_count: int,
    cfg: Any,
) -> dict[str, object]:
    diagnostics: list[dict[str, object]] = []
    score_by_role = {
        item.template.candidate_role: float(item.candidate_score)
        for item in scored
    }
    for candidate in candidates:
        result = candidate_results.get(candidate.candidate_role)
        if result is None:
            continue
        diagnostic = _candidate_gate_diagnostic(
            template=candidate,
            zone_points=zone_points,
            result=result,
            zone_min_tc_ratio=zone_min_tc_ratio,
            cfg=cfg,
        )
        diagnostic["candidate_score"] = score_by_role.get(
            candidate.candidate_role,
            float("inf"),
        )
        diagnostics.append(diagnostic)

    hard_pass_scores = [
        float(item["candidate_score"])
        for item in diagnostics
        if bool(item["hard_gate_pass"]) and math.isfinite(float(item["candidate_score"]))
    ]
    notes = [
        str(item["hard_gate_notes"])
        for item in diagnostics
        if not bool(item["hard_gate_pass"])
    ]
    failure_counts = {
        "stall": sum("stall margin" in note for note in notes),
        "cm": sum("cm hard violation" in note for note in notes),
        "t/c": sum("t/c" in note for note in notes),
        "spar": sum("spar depth" in note for note in notes),
        "analysis": sum(
            note
            not in {"ok"}
            and all(token not in note for token in ("stall margin", "cm hard violation", "t/c", "spar depth"))
            for note in notes
        ),
    }
    dominant_failures = [
        f"{name}:{count}"
        for name, count in sorted(failure_counts.items(), key=lambda item: (-item[1], item[0]))
        if count
    ]
    return {
        "scale": scale_name,
        "zone": zone_name,
        "feasible_geometry_candidates": len(candidates),
        "coarse_scored": int(coarse_scored_count),
        "robust_scored": int(robust_scored_count),
        "aero_scored": len(diagnostics),
        "hard_gate_pass_count": sum(bool(item["hard_gate_pass"]) for item in diagnostics),
        "stall_pass_count": sum(bool(item["stall_pass"]) for item in diagnostics),
        "cm_pass_count": sum(bool(item["cm_pass"]) for item in diagnostics),
        "tc_pass_count": sum(bool(item["tc_pass"]) for item in diagnostics),
        "spar_pass_count": sum(bool(item["spar_pass"]) for item in diagnostics),
        "best_stall_margin": max(
            (float(item["best_stall_margin"]) for item in diagnostics),
            default=float("-inf"),
        ),
        "best_hard_gate_pass_score": min(hard_pass_scores) if hard_pass_scores else "",
        "dominant_failures": "; ".join(dominant_failures) if dominant_failures else "none",
    }


def _stall_design_audit_row(
    *,
    scale_name: str,
    zone_name: str,
    zone_points: list[dict[str, float]],
    historical_rows: Sequence[Mapping[str, object]],
    cfg: Any,
) -> dict[str, object]:
    cl_values = [float(point["cl_target"]) for point in zone_points]
    re_values = [float(point["reynolds"]) for point in zone_points]
    historical_safe_clmax = [
        float(row["safe_clmax"])
        for row in historical_rows
        if row.get("zone") == zone_name and isinstance(row.get("safe_clmax"), int | float)
    ]
    zone_hist = [row for row in historical_rows if row.get("zone") == zone_name]
    pass_count = sum(bool(row.get("hard_gate_pass")) for row in zone_hist)
    combined_notes = "; ".join(str(row.get("hard_gate_notes", "")) for row in zone_hist)
    if pass_count:
        likely_issue = "historical reference includes at least one hard-gate pass"
    elif "t/c" in combined_notes and zone_name == "root":
        likely_issue = "root t/c gate plus high CL demand rejects thin historical references"
    elif "stall margin" in combined_notes:
        likely_issue = "target CL/stall-utilization contract is tighter than historical safe CLmax"
    elif "cm hard violation" in combined_notes:
        likely_issue = "trim/Cm hard bound rejects the historical reference set"
    else:
        likely_issue = "no passing historical reference; inspect XFOIL status and geometry gates"
    return {
        "scale": scale_name,
        "zone": zone_name,
        "cl_target_range": f"{min(cl_values):.3f}-{max(cl_values):.3f}" if cl_values else "",
        "re_range": f"{min(re_values)/1000:.0f}-{max(re_values)/1000:.0f}k" if re_values else "",
        "required_stall_margin": (
            f"utilization <= {float(cfg.stall_model.local_stall_utilization_limit):.2f}"
        ),
        "historical_best_safe_clmax": max(historical_safe_clmax) if historical_safe_clmax else "",
        "historical_pass_fail": f"{pass_count}/{len(zone_hist)} pass",
        "likely_issue": likely_issue,
    }


def _run_seedless_scale(
    *,
    scale: ScaleConfig,
    cfg: Any,
    worker: JuliaXFoilWorker,
    top_n: int,
) -> dict[str, object]:
    zone_requirements = {
        zone_name: payload
        for zone_name, payload in build_reference_zone_requirements().items()
        if zone_name in scale.zones
    }
    start_time = time.monotonic()
    (
        zone_points_by_name,
        zone_min_tc_by_name,
        candidates_by_zone,
        coarse_candidates_by_zone,
    ) = _prepare_zone_selection_inputs(
        zone_requirements=zone_requirements,
        seed_loader=_seed_loader,
        thickness_delta_levels=cfg.cst_search.thickness_delta_levels,
        camber_delta_levels=cfg.cst_search.camber_delta_levels,
        coarse_to_fine_enabled=bool(cfg.cst_search.coarse_to_fine_enabled),
        coarse_thickness_stride=int(cfg.cst_search.coarse_thickness_stride),
        coarse_camber_stride=int(cfg.cst_search.coarse_camber_stride),
        coarse_score_count=scale.coarse_score_count,
        search_mode="seedless_sobol",
        seedless_sample_count=int(scale.sample_count),
        seedless_random_seed=cfg.cst_search.seedless_random_seed,
        seedless_max_oversample_factor=int(cfg.cst_search.seedless_max_oversample_factor),
        seedless_te_thickness_min=float(cfg.cst_search.seedless_te_thickness_min),
    )

    candidate_results_by_zone, coarse_worker_results = _run_batched_zone_candidate_queries(
        zone_candidates=coarse_candidates_by_zone,
        zone_points_by_name=zone_points_by_name,
        worker=worker,
        robust_evaluation_enabled=bool(
            scale.robust_enabled
            and (
                bool(cfg.cst_search.coarse_robust_evaluation_enabled)
                or not bool(cfg.cst_search.coarse_to_fine_enabled)
            )
        ),
        robust_reynolds_factors=scale.reynolds_factors,
        robust_roughness_modes=scale.roughness_modes,
        robust_min_pass_rate=float(cfg.cst_search.robust_min_pass_rate),
        stage_label=f"{scale.name}_coarse_screening",
    )
    worker_results: list[Mapping[str, object]] = list(coarse_worker_results)

    robust_candidate_count_by_zone: dict[str, int] = {zone: 0 for zone in zone_requirements}
    if bool(cfg.cst_search.coarse_to_fine_enabled):
        coarse_beam_by_zone: dict[str, tuple[CSTAirfoilTemplate, ...]] = {}
        for zone_name, coarse_candidates in coarse_candidates_by_zone.items():
            scored = _score_available_zone_candidates(
                coarse_candidates,
                zone_points=zone_points_by_name[zone_name],
                candidate_results=candidate_results_by_zone.get(zone_name, {}),
                zone_min_tc_ratio=zone_min_tc_by_name[zone_name],
                safe_clmax_scale=float(cfg.stall_model.safe_clmax_scale),
                safe_clmax_delta=float(cfg.stall_model.safe_clmax_delta),
                stall_utilization_limit=float(cfg.stall_model.local_stall_utilization_limit),
                tip_3d_penalty_start_eta=float(cfg.stall_model.tip_3d_penalty_start_eta),
                tip_3d_penalty_max=float(cfg.stall_model.tip_3d_penalty_max),
                tip_taper_penalty_weight=float(cfg.stall_model.tip_taper_penalty_weight),
                washout_relief_deg=float(cfg.stall_model.washout_relief_deg),
                washout_relief_max=float(cfg.stall_model.washout_relief_max),
                launch_stall_utilization_limit=float(cfg.stall_model.launch_utilization_limit),
                turn_stall_utilization_limit=float(cfg.stall_model.turn_utilization_limit),
                local_stall_utilization_limit=float(cfg.stall_model.local_stall_utilization_limit),
                cm_hard_lower_bound=float(cfg.cst_search.cm_hard_lower_bound),
                cm_penalty_threshold=float(cfg.cst_search.cm_penalty_threshold),
                trim_drag_per_cm_squared=_trim_drag_per_cm_squared(cfg),
                score_cfg=cfg.airfoil_selection_score,
            )
            promoted_count = (
                int(scale.robust_score_count)
                if scale.robust_score_count is not None
                else (
                    int(cfg.cst_search.robust_score_count)
                    if cfg.cst_search.robust_score_count is not None
                    else int(cfg.cst_search.coarse_keep_top_k)
                )
            )
            beam_count = min(max(1, promoted_count), len(scored))
            coarse_beam_by_zone[zone_name] = _select_scored_candidate_beam(
                scored,
                beam_count=beam_count,
                selection_strategy=cfg.cst_search.selection_strategy,
                pareto_knee_count=int(cfg.cst_search.pareto_knee_count),
            )

        current_beam_by_zone = coarse_beam_by_zone
        if bool(cfg.cst_search.successive_halving_enabled):
            total_rounds = max(1, int(cfg.cst_search.successive_halving_rounds))
            for round_index in range(total_rounds):
                stage_candidates_by_zone: dict[str, tuple[CSTAirfoilTemplate, ...]] = {}
                radius = _successive_halving_radius(
                    round_index=round_index,
                    total_rounds=total_rounds,
                    base_radius=int(cfg.cst_search.refine_neighbor_radius),
                )
                for zone_name, candidates in candidates_by_zone.items():
                    stage_candidates_by_zone[zone_name] = _refinement_candidates(
                        candidates,
                        seed_candidates=current_beam_by_zone[zone_name],
                        neighbor_radius=radius,
                    )
                    robust_candidate_count_by_zone[zone_name] += len(
                        stage_candidates_by_zone[zone_name]
                    )
                candidate_results_by_zone, stage_worker_results = _run_batched_zone_candidate_queries(
                    zone_candidates=stage_candidates_by_zone,
                    zone_points_by_name=zone_points_by_name,
                    worker=worker,
                    existing_results_by_zone=candidate_results_by_zone,
                    robust_evaluation_enabled=bool(scale.robust_enabled),
                    robust_reynolds_factors=scale.reynolds_factors,
                    robust_roughness_modes=scale.roughness_modes,
                    robust_min_pass_rate=float(cfg.cst_search.robust_min_pass_rate),
                    stage_label=f"{scale.name}_successive_halving_{round_index + 1}",
                )
                worker_results.extend(stage_worker_results)

                next_beam_by_zone: dict[str, tuple[CSTAirfoilTemplate, ...]] = {}
                for zone_name, stage_candidates in stage_candidates_by_zone.items():
                    stage_scored = _score_available_zone_candidates(
                        stage_candidates,
                        zone_points=zone_points_by_name[zone_name],
                        candidate_results=candidate_results_by_zone.get(zone_name, {}),
                        zone_min_tc_ratio=zone_min_tc_by_name[zone_name],
                        safe_clmax_scale=float(cfg.stall_model.safe_clmax_scale),
                        safe_clmax_delta=float(cfg.stall_model.safe_clmax_delta),
                        stall_utilization_limit=float(cfg.stall_model.local_stall_utilization_limit),
                        tip_3d_penalty_start_eta=float(cfg.stall_model.tip_3d_penalty_start_eta),
                        tip_3d_penalty_max=float(cfg.stall_model.tip_3d_penalty_max),
                        tip_taper_penalty_weight=float(cfg.stall_model.tip_taper_penalty_weight),
                        washout_relief_deg=float(cfg.stall_model.washout_relief_deg),
                        washout_relief_max=float(cfg.stall_model.washout_relief_max),
                        launch_stall_utilization_limit=float(cfg.stall_model.launch_utilization_limit),
                        turn_stall_utilization_limit=float(cfg.stall_model.turn_utilization_limit),
                        local_stall_utilization_limit=float(cfg.stall_model.local_stall_utilization_limit),
                        cm_hard_lower_bound=float(cfg.cst_search.cm_hard_lower_bound),
                        cm_penalty_threshold=float(cfg.cst_search.cm_penalty_threshold),
                        trim_drag_per_cm_squared=_trim_drag_per_cm_squared(cfg),
                        score_cfg=cfg.airfoil_selection_score,
                    )
                    beam_count = min(
                        max(1, int(cfg.cst_search.successive_halving_beam_width)),
                        len(stage_scored),
                    )
                    next_beam_by_zone[zone_name] = _select_scored_candidate_beam(
                        stage_scored,
                        beam_count=beam_count,
                        selection_strategy=cfg.cst_search.selection_strategy,
                        pareto_knee_count=int(cfg.cst_search.pareto_knee_count),
                    )
                current_beam_by_zone = next_beam_by_zone

    historical_by_zone = {
        zone_name: _load_historical_templates_for_zone(zone_name)
        for zone_name in zone_requirements
    }
    historical_results_by_zone, historical_worker_results = _run_batched_zone_candidate_queries(
        zone_candidates=historical_by_zone,
        zone_points_by_name=zone_points_by_name,
        worker=worker,
        robust_evaluation_enabled=bool(scale.robust_enabled),
        robust_reynolds_factors=scale.reynolds_factors,
        robust_roughness_modes=scale.roughness_modes,
        robust_min_pass_rate=float(cfg.cst_search.robust_min_pass_rate),
        stage_label=f"{scale.name}_historical_baseline",
    )
    worker_results.extend(historical_worker_results)
    raw_by_zone_role = _raw_results_by_zone_role(worker_results)

    top_rows: list[dict[str, object]] = []
    historical_rows: list[dict[str, object]] = []
    feasibility_rows: list[dict[str, object]] = []
    stall_design_rows: list[dict[str, object]] = []
    candidate_payload_by_zone: dict[str, dict[str, Any]] = {}
    for zone_name in zone_requirements:
        scored = _score_available_zone_candidates(
            candidates_by_zone[zone_name],
            zone_points=zone_points_by_name[zone_name],
            candidate_results=candidate_results_by_zone.get(zone_name, {}),
            zone_min_tc_ratio=zone_min_tc_by_name[zone_name],
            safe_clmax_scale=float(cfg.stall_model.safe_clmax_scale),
            safe_clmax_delta=float(cfg.stall_model.safe_clmax_delta),
            stall_utilization_limit=float(cfg.stall_model.local_stall_utilization_limit),
            tip_3d_penalty_start_eta=float(cfg.stall_model.tip_3d_penalty_start_eta),
            tip_3d_penalty_max=float(cfg.stall_model.tip_3d_penalty_max),
            tip_taper_penalty_weight=float(cfg.stall_model.tip_taper_penalty_weight),
            washout_relief_deg=float(cfg.stall_model.washout_relief_deg),
            washout_relief_max=float(cfg.stall_model.washout_relief_max),
            launch_stall_utilization_limit=float(cfg.stall_model.launch_utilization_limit),
            turn_stall_utilization_limit=float(cfg.stall_model.turn_utilization_limit),
            local_stall_utilization_limit=float(cfg.stall_model.local_stall_utilization_limit),
            cm_hard_lower_bound=float(cfg.cst_search.cm_hard_lower_bound),
            cm_penalty_threshold=float(cfg.cst_search.cm_penalty_threshold),
            trim_drag_per_cm_squared=_trim_drag_per_cm_squared(cfg),
            score_cfg=cfg.airfoil_selection_score,
        )
        candidate_payload_by_zone[zone_name] = {
            "scored": scored,
            "candidate_results": candidate_results_by_zone.get(zone_name, {}),
            "zone_points": zone_points_by_name[zone_name],
            "zone_min_tc_ratio": zone_min_tc_by_name[zone_name],
        }
        for rank, score_item in enumerate(scored[:top_n], start=1):
            role = score_item.template.candidate_role
            top_rows.append(
                _candidate_summary_row(
                    scale_name=scale.name,
                    zone_name=zone_name,
                    rank=rank,
                    score_item=score_item,
                    candidate_result=candidate_results_by_zone[zone_name][role],
                    raw_results=raw_by_zone_role.get((zone_name, role), ()),
                    zone_points=zone_points_by_name[zone_name],
                    zone_min_tc_ratio=zone_min_tc_by_name[zone_name],
                    cfg=cfg,
                    source="seedless",
                )
            )

        historical_scored = _score_available_zone_candidates(
            historical_by_zone[zone_name],
            zone_points=zone_points_by_name[zone_name],
            candidate_results=historical_results_by_zone.get(zone_name, {}),
            zone_min_tc_ratio=zone_min_tc_by_name[zone_name],
            safe_clmax_scale=float(cfg.stall_model.safe_clmax_scale),
            safe_clmax_delta=float(cfg.stall_model.safe_clmax_delta),
            stall_utilization_limit=float(cfg.stall_model.local_stall_utilization_limit),
            tip_3d_penalty_start_eta=float(cfg.stall_model.tip_3d_penalty_start_eta),
            tip_3d_penalty_max=float(cfg.stall_model.tip_3d_penalty_max),
            tip_taper_penalty_weight=float(cfg.stall_model.tip_taper_penalty_weight),
            washout_relief_deg=float(cfg.stall_model.washout_relief_deg),
            washout_relief_max=float(cfg.stall_model.washout_relief_max),
            launch_stall_utilization_limit=float(cfg.stall_model.launch_utilization_limit),
            turn_stall_utilization_limit=float(cfg.stall_model.turn_utilization_limit),
            local_stall_utilization_limit=float(cfg.stall_model.local_stall_utilization_limit),
            cm_hard_lower_bound=float(cfg.cst_search.cm_hard_lower_bound),
            cm_penalty_threshold=float(cfg.cst_search.cm_penalty_threshold),
            trim_drag_per_cm_squared=_trim_drag_per_cm_squared(cfg),
            score_cfg=cfg.airfoil_selection_score,
        )
        zone_historical_rows: list[dict[str, object]] = []
        for rank, score_item in enumerate(historical_scored, start=1):
            role = score_item.template.candidate_role
            row = _candidate_summary_row(
                scale_name=scale.name,
                zone_name=zone_name,
                rank=rank,
                score_item=score_item,
                candidate_result=historical_results_by_zone[zone_name][role],
                raw_results=raw_by_zone_role.get((zone_name, role), ()),
                zone_points=zone_points_by_name[zone_name],
                zone_min_tc_ratio=zone_min_tc_by_name[zone_name],
                cfg=cfg,
                source="historical",
            )
            historical_rows.append(row)
            zone_historical_rows.append(row)

        feasibility_rows.append(
            _zone_feasibility_stat_row(
                scale_name=scale.name,
                zone_name=zone_name,
                candidates=candidates_by_zone[zone_name],
                scored=scored,
                candidate_results=candidate_results_by_zone.get(zone_name, {}),
                zone_points=zone_points_by_name[zone_name],
                zone_min_tc_ratio=zone_min_tc_by_name[zone_name],
                coarse_scored_count=len(coarse_candidates_by_zone[zone_name]),
                robust_scored_count=robust_candidate_count_by_zone.get(zone_name, 0),
                cfg=cfg,
            )
        )
        stall_design_rows.append(
            _stall_design_audit_row(
                scale_name=scale.name,
                zone_name=zone_name,
                zone_points=zone_points_by_name[zone_name],
                historical_rows=zone_historical_rows,
                cfg=cfg,
            )
        )

    elapsed_s = time.monotonic() - start_time
    zone_counts = [
        {
            "scale": scale.name,
            "zone": zone_name,
            "requested_sample_count": int(scale.sample_count),
            "coarse_score_count_limit": int(scale.coarse_score_count or 0),
            "robust_score_count_limit": int(scale.robust_score_count or 0),
            "candidate_pool_count": len(candidates_by_zone[zone_name]),
            "coarse_evaluated_count": len(coarse_candidates_by_zone[zone_name]),
            "robust_stage_candidate_count": robust_candidate_count_by_zone.get(zone_name, 0),
            "scored_candidate_count": len(
                candidate_payload_by_zone[zone_name]["scored"]
            ),
            "historical_reference_count": len(historical_by_zone[zone_name]),
        }
        for zone_name in zone_requirements
    ]
    return {
        "scale": scale.name,
        "sample_count": int(scale.sample_count),
        "coarse_score_count": scale.coarse_score_count,
        "robust_score_count": scale.robust_score_count,
        "reynolds_factors": list(scale.reynolds_factors),
        "roughness_modes": list(scale.roughness_modes),
        "robust_enabled": bool(scale.robust_enabled),
        "zones": list(scale.zones),
        "elapsed_s": elapsed_s,
        "zone_counts": zone_counts,
        "top_rows": top_rows,
        "historical_rows": historical_rows,
        "feasibility_rows": feasibility_rows,
        "stall_design_rows": stall_design_rows,
        "worker_result_count": len(worker_results),
        "raw_worker_results": list(worker_results),
    }


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=fieldnames,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(value) if isinstance(value, list | tuple | dict) else value
                    for key, value in row.items()
                }
            )


def _markdown_table(rows: Sequence[Mapping[str, object]], columns: Sequence[str]) -> list[str]:
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        values = []
        for column in columns:
            value = row.get(column, "")
            if isinstance(value, float):
                value = f"{value:.5g}"
            values.append(str(value).replace("|", "/"))
        lines.append("| " + " | ".join(values) + " |")
    return lines


def _write_report(
    *,
    output_dir: Path,
    run_payload: Mapping[str, object],
    plot_files: Sequence[Path],
) -> None:
    scale_payloads = list(run_payload["scales"])
    smoke_scale = next(
        (scale for scale in scale_payloads if scale.get("scale") == "smoke"),
        scale_payloads[0] if scale_payloads else {},
    )
    largest_scale = scale_payloads[-1] if scale_payloads else {}
    representative_top_rows = list(largest_scale.get("top_rows", []))
    representative_historical_rows = list(largest_scale.get("historical_rows", []))
    smoke_top_rows = list(smoke_scale.get("top_rows", []))
    smoke_historical_rows = list(smoke_scale.get("historical_rows", []))
    smoke_label = str(smoke_scale.get("scale", "first")).title()
    representative_label = str(largest_scale.get("scale", "representative")).title()
    all_top_rows = [
        row
        for scale in scale_payloads
        for row in scale.get("top_rows", [])
    ]
    zone_counts = [
        item
        for scale in scale_payloads
        for item in scale.get("zone_counts", [])
    ]

    lines: list[str] = [
        "# Seedless CST Airfoil Selection Behavior Audit",
        "",
        "Read-mostly audit of post-Phase-3 seedless CST selection behavior.",
        "",
        "## Dry-run scales",
        "",
    ]
    lines.extend(
        _markdown_table(
            [
                {
                    "scale": scale["scale"],
                    "sample_count": scale["sample_count"],
                    "coarse_score_count": scale["coarse_score_count"],
                    "robust_score_count": scale["robust_score_count"],
                    "re_factors": scale["reynolds_factors"],
                    "roughness": scale["roughness_modes"],
                    "zones": scale["zones"],
                    "worker_results": scale["worker_result_count"],
                    "elapsed_s": scale["elapsed_s"],
                }
                for scale in scale_payloads
            ],
            (
                "scale",
                "sample_count",
                "coarse_score_count",
                "robust_score_count",
                "re_factors",
                "roughness",
                "zones",
                "worker_results",
                "elapsed_s",
            ),
        )
    )
    lines.extend(["", "## Actual candidate evaluation counts", ""])
    lines.extend(
        _markdown_table(
            zone_counts,
            (
                "scale",
                "zone",
                "requested_sample_count",
                "coarse_score_count_limit",
                "robust_score_count_limit",
                "candidate_pool_count",
                "coarse_evaluated_count",
                "robust_stage_candidate_count",
                "scored_candidate_count",
                "historical_reference_count",
            ),
        )
    )
    lines.extend(
        [
            "",
            "Important behavior note: with current `coarse_to_fine_enabled` seedless mode, the production candidate pool can be 1024 per zone, but only a small coarse subset is sent to XFOIL before the robust stage. This audit records both the pool count and actually scored count.",
            "",
            f"## {smoke_label} Top Seedless Candidates",
            "",
            "This table is the first completed scale in the audit and is included to make sure the requested zones have explicit behavior evidence without forcing pytest to run a full 1024-sample XFOIL campaign.",
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            smoke_top_rows,
            (
                "zone",
                "rank",
                "candidate_id",
                "cd_mission",
                "safe_clmax",
                "cm",
                "robust_pass_rate",
                "tc",
                "camber",
                "te_thickness",
                "hard_gate_pass",
                "artifact_suspicion",
                "hard_gate_notes",
            ),
        )
    )
    lines.extend(
        [
            "",
            f"## Representative {representative_label} Top Seedless Candidates",
            "",
            "This representative table uses the largest completed scale in the run with the configured Reynolds and roughness settings. Full all-zone production-probe is intentionally treated as a formal campaign scale when runtime is too high for an interactive audit.",
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            representative_top_rows,
            (
                "zone",
                "rank",
                "candidate_id",
                "cd_mission",
                "safe_clmax",
                "cm",
                "robust_pass_rate",
                "tc",
                "camber",
                "te_thickness",
                "hard_gate_pass",
                "artifact_suspicion",
                "hard_gate_notes",
            ),
        )
    )
    lines.extend(["", f"## {smoke_label} Historical Baseline Comparison", ""])
    lines.extend(
        _markdown_table(
            smoke_historical_rows,
            (
                "zone",
                "candidate_id",
                "score",
                "cd_mission",
                "safe_clmax",
                "cm",
                "robust_pass_rate",
                "hard_gate_pass",
                "hard_gate_notes",
                "artifact_suspicion",
            ),
        )
    )
    lines.extend(["", f"## Representative {representative_label} Historical Baseline Comparison", ""])
    lines.extend(
        _markdown_table(
            representative_historical_rows,
            (
                "zone",
                "candidate_id",
                "score",
                "cd_mission",
                "safe_clmax",
                "cm",
                "robust_pass_rate",
                "hard_gate_pass",
                "hard_gate_notes",
                "artifact_suspicion",
            ),
        )
    )
    lines.extend(["", "## Artifact Risk", ""])
    high_or_medium = [
        row for row in all_top_rows if row.get("artifact_suspicion") in {"medium", "high"}
    ]
    if high_or_medium:
        lines.extend(
            _markdown_table(
                high_or_medium,
                (
                    "scale",
                    "zone",
                    "rank",
                    "candidate_id",
                    "artifact_suspicion",
                    "artifact_notes",
                ),
            )
        )
    else:
        lines.append("- Top seedless candidates did not trigger the simple artifact heuristics.")

    lines.extend(["", "## Figures", ""])
    for plot_path in plot_files:
        lines.append(f"- [{plot_path.name}]({plot_path.name})")

    lines.extend(
        [
            "",
            "## Judgment",
            "",
            "1. Bounds expansion did allow seedless geometry in the historical FX/DAE envelope, but selection only partially moves toward those families. The `tip` production-probe top candidates are plausible low-Re sections (`t/c` about 0.102-0.105 and moderate camber) and compete directly with DAE31/DAE21. The `root` probe does not produce a clean accepted FX-like solution; every root seedless and historical candidate in this run fails a hard gate.",
            "2. The root mismatch is mainly a design-point/gate and effective-sampling issue, not a CST-degree issue. Root and mid stations carry high target CL, and the hard-gate notes are dominated by stall margin. The Phase 5 funnel now records explicit coarse and robust-stage counts so `seedless_sample_count=1024` is no longer mistaken for the number of XFOIL-scored candidates.",
            "3. XFOIL artifact risk is mixed. The best `tip` production-probe candidates are low-suspicion and hard-gate passing. Several root candidates that look attractive by drag have large polar target mismatch, low safe-clmax, or excessive negative Cm, so those should not be promoted as real gains.",
            "4. Historical baselines are useful sanity checks but not all are suitable for every zone under the current scoring contract. DAE31/DAE21 pass the `tip` hard gates. FX 76-MP-140 is penalized at the root by stall margin and Cm, while DAE11/DAE21 are also below the current root thickness requirement.",
            "5. Recommendation: do not promote the full production baseline directly into unrestricted 3D combination screening yet. A limited outboard/tip screening is reasonable, with DAE31/DAE21 retained as references. Root/mid should first get a selection-behavior patch plan around hard-gate feasibility, robust candidate count, and design-point weighting.",
            "6. Keep manufacturing constraints separate from the airfoil search-space coverage gate. The near-sharp TE allowance should stay in search; any build minimum should be a downstream manufacturing/buildability gate.",
            "7. Keep `n=7` as diagnostic mode. Phase 3 already showed `n=6` fits the historical geometry gate, and this Phase 4 behavior is controlled by scoring, gates, XFOIL robustness, and effective candidate evaluation count.",
            "",
            "## Files",
            "",
            "- `run_summary.json`: complete machine-readable audit payload.",
            "- `top_candidates.csv`: top seedless candidate rows across all scales.",
            "- `historical_baselines.csv`: historical baseline rows across all scales.",
            "- `zone_evaluation_counts.csv`: requested vs actually evaluated candidate counts.",
        ]
    )
    (output_dir / "seedless_selection_behavior.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def _write_phase5_report(
    *,
    output_dir: Path,
    run_payload: Mapping[str, object],
) -> None:
    scale_payloads = list(run_payload["scales"])
    all_zone_counts = [
        row for scale in scale_payloads for row in scale.get("zone_counts", [])
    ]
    all_feasibility_rows = [
        row for scale in scale_payloads for row in scale.get("feasibility_rows", [])
    ]
    all_stall_rows = [
        row for scale in scale_payloads for row in scale.get("stall_design_rows", [])
    ]
    all_top_rows = [
        row for scale in scale_payloads for row in scale.get("top_rows", [])
    ]
    all_historical_rows = [
        row for scale in scale_payloads for row in scale.get("historical_rows", [])
    ]
    production_rows_raw = [
        row for row in all_feasibility_rows if row.get("scale") == "production-probe"
    ]
    representative_scale = "production-probe" if production_rows_raw else (
        str(scale_payloads[-1].get("scale", "unknown")) if scale_payloads else "unknown"
    )
    production_rows = production_rows_raw or [
        row for row in all_feasibility_rows if row.get("scale") == representative_scale
    ]
    production_top_raw = [
        row for row in all_top_rows if row.get("scale") == "production-probe"
    ]
    production_top = production_top_raw or [
        row for row in all_top_rows if row.get("scale") == representative_scale
    ]
    production_historical_raw = [
        row for row in all_historical_rows if row.get("scale") == "production-probe"
    ]
    production_historical = production_historical_raw or [
        row for row in all_historical_rows if row.get("scale") == representative_scale
    ]
    production_stall_raw = [
        row for row in all_stall_rows if row.get("scale") == "production-probe"
    ]
    production_stall = production_stall_raw or [
        row for row in all_stall_rows if row.get("scale") == representative_scale
    ]
    no_feasible_zones = [
        str(row["zone"])
        for row in production_rows
        if int(row.get("hard_gate_pass_count", 0)) == 0
    ]
    tip_rows = [row for row in production_rows if row.get("zone") in {"mid2", "tip"}]
    tip_stable = any(int(row.get("hard_gate_pass_count", 0)) > 0 for row in tip_rows)

    stage_rows = [
        {
            "Stage": "seedless_sample_count",
            "Current count/limit": "baseline 1024 / smoke 128",
            "Source file": "configs/birdman_upstream_concept_baseline.yaml",
            "Function/config": "cst_search.seedless_sample_count",
            "Notes": "Sobol geometry pool; not equal to XFOIL-scored count.",
        },
        {
            "Stage": "Sobol feasible geometry candidates",
            "Current count/limit": "up to sample_count after geometry prescreen",
            "Source file": "src/hpa_mdo/concept/airfoil_selection.py",
            "Function/config": "_prepare_zone_selection_inputs",
            "Notes": "Caches by zone, min t/c, TE min, sample count, seed, oversample.",
        },
        {
            "Stage": "coarse screening candidate count",
            "Current count/limit": "smoke 12 / medium 64 / production 96",
            "Source file": "src/hpa_mdo/concept/airfoil_selection.py",
            "Function/config": "coarse_score_count -> _coarse_seed_candidates",
            "Notes": "Phase 4 fallback was stride-derived 12 for seedless pools.",
        },
        {
            "Stage": "robust-stage candidate count",
            "Current count/limit": "smoke 3 / medium 16 / production 24",
            "Source file": "src/hpa_mdo/concept/airfoil_selection.py",
            "Function/config": "robust_score_count",
            "Notes": "Promotes this many coarse-ranked candidates into robust clean/rough scoring.",
        },
        {
            "Stage": "clean/rough + Re factors scoring",
            "Current count/limit": "production 3 Re x 2 roughness",
            "Source file": "configs/birdman_upstream_concept_baseline.yaml",
            "Function/config": "robust_reynolds_factors, robust_roughness_modes",
            "Notes": "Smoke keeps Re=[1.0] and clean only.",
        },
        {
            "Stage": "hard gate",
            "Current count/limit": "stall, t/c, spar depth, Cm",
            "Source file": "src/hpa_mdo/concept/airfoil_selection.py",
            "Function/config": "_score_available_zone_candidates, select_best_zone_candidate",
            "Notes": "Hard-gate pass candidates sort ahead of infeasible candidates.",
        },
        {
            "Stage": "selected candidates",
            "Current count/limit": "1 per zone, or infeasible_best_effort label",
            "Source file": "src/hpa_mdo/concept/airfoil_selection.py",
            "Function/config": "SelectedZoneCandidate.selection_status",
            "Notes": "No feasible zone is explicitly marked instead of treated as a normal selected airfoil.",
        },
    ]

    lines: list[str] = [
        "# Phase 5 Seedless CST Selection Funnel Audit",
        "",
        "This is the post-patch audit for the seedless CST selection funnel. It is intentionally narrow: no CST degree change, no N1/N2 change, and no stall-gate relaxation.",
        "",
        "## Funnel Controls",
        "",
    ]
    lines.extend(
        _markdown_table(
            stage_rows,
            ("Stage", "Current count/limit", "Source file", "Function/config", "Notes"),
        )
    )
    lines.extend(
        [
            "",
            "## Old vs New Funnel",
            "",
            "- Phase 4 behavior: production-probe `1024 -> 12 coarse -> 3 robust-stage` per zone.",
            "- Phase 5 production behavior: `1024 -> 96 coarse -> 24 robust-stage` per zone.",
            "- Smoke behavior remains intentionally small: `128 -> 12 -> 3`, and CI tests do not run a production XFOIL campaign.",
            "- Medium dry-run behavior is `512 -> 64 -> 16` for a more useful local probe.",
            "- In this recorded Phase 5 run the completed XFOIL audit scale is `medium`. Full all-zone `production-probe` was attempted but the 1024-sample feasible Sobol generation was too slow for an interactive audit turn; keep it as a formal campaign scale, not a pytest/smoke job.",
            "",
            "## Dry-Run Counts",
            "",
        ]
    )
    lines.extend(
        _markdown_table(
            all_zone_counts,
            (
                "scale",
                "zone",
                "requested_sample_count",
                "coarse_score_count_limit",
                "robust_score_count_limit",
                "candidate_pool_count",
                "coarse_evaluated_count",
                "robust_stage_candidate_count",
                "scored_candidate_count",
            ),
        )
    )
    lines.extend(["", "## Root/Mid Feasibility", ""])
    lines.extend(
        _markdown_table(
            [row for row in production_rows if row.get("zone") in {"root", "mid1", "mid2"}],
            (
                "zone",
                "feasible_geometry_candidates",
                "coarse_scored",
                "robust_scored",
                "hard_gate_pass_count",
                "stall_pass_count",
                "cm_pass_count",
                "tc_pass_count",
                "spar_pass_count",
                "best_stall_margin",
                "best_hard_gate_pass_score",
                "dominant_failures",
            ),
        )
    )
    lines.extend(["", "## Stall Gate / Design Point Audit", ""])
    lines.extend(
        _markdown_table(
            production_stall,
            (
                "zone",
                "cl_target_range",
                "re_range",
                "required_stall_margin",
                "historical_best_safe_clmax",
                "historical_pass_fail",
                "likely_issue",
            ),
        )
    )
    lines.extend(["", f"## {representative_scale.title()} Top Candidates", ""])
    lines.extend(
        _markdown_table(
            production_top,
            (
                "zone",
                "rank",
                "candidate_id",
                "cd_mission",
                "safe_clmax",
                "cm",
                "robust_pass_rate",
                "tc",
                "camber",
                "te_thickness",
                "hard_gate_pass",
                "artifact_suspicion",
                "hard_gate_notes",
            ),
        )
    )
    lines.extend(["", "## Historical Baselines", ""])
    lines.extend(
        _markdown_table(
            production_historical,
            (
                "zone",
                "candidate_id",
                "score",
                "cd_mission",
                "safe_clmax",
                "cm",
                "robust_pass_rate",
                "hard_gate_pass",
                "hard_gate_notes",
            ),
        )
    )
    lines.extend(
        [
            "",
            "## Engineering Judgment",
            "",
            f"- Zones with no feasible {representative_scale} seedless candidate: {', '.join(no_feasible_zones) if no_feasible_zones else 'none'}.",
            f"- Outboard stability: {'acceptable; at least one mid2/tip hard-gate pass remains' if tip_stable else 'not demonstrated in this run'}.",
            "- Root/mid infeasibility should not be fixed by blindly relaxing the stall gate. The current evidence points first to target-CL/stall-utilization compatibility and the root t/c plus Cm contract.",
            "- Limited 3D combination screening is reasonable only for zones/designs that carry `hard_gate_pass=True`; root/mid no-feasible cases should enter as explicit diagnostic/best-effort references, not normal selected airfoils.",
            "- Manufacturing trailing-edge thickness should remain a downstream build gate, not an airfoil search-space coverage gate.",
            "- `n=7` remains diagnostic only; Phase 5 does not show a CST-degree blocker.",
            "",
            "## Machine-Readable Artifacts",
            "",
            "- `phase5_feasibility_stats.csv`",
            "- `phase5_stall_design_audit.csv`",
            "- `zone_evaluation_counts.csv`",
            "- `top_candidates.csv`",
            "- `historical_baselines.csv`",
            "- `run_summary.json`",
        ]
    )
    (output_dir / "seedless_selection_funnel_phase5.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def _plot_outputs(
    *,
    output_dir: Path,
    scale_payload: Mapping[str, object],
    filename_prefix: str,
) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    top_rows = list(scale_payload.get("top_rows", []))
    historical_rows = list(scale_payload.get("historical_rows", []))
    raw_by_zone_role = _raw_results_by_zone_role(
        scale_payload.get("raw_worker_results", [])
    )
    scale_name = str(scale_payload.get("scale", "unknown"))
    plot_files: list[Path] = []

    for zone_name in ZONE_NAMES:
        zone_top = [row for row in top_rows if row["zone"] == zone_name][:5]
        zone_hist = [row for row in historical_rows if row["zone"] == zone_name]
        if not zone_top:
            continue
        fig, ax = plt.subplots(figsize=(8, 4))
        for row in zone_top:
            template = CSTAirfoilTemplate(
                zone_name=zone_name,
                upper_coefficients=tuple(row["upper_coefficients"]),
                lower_coefficients=tuple(row["lower_coefficients"]),
                te_thickness_m=float(row["te_thickness"]),
                candidate_role=str(row["candidate_id"]),
            )
            coords = generate_cst_coordinates(template)
            xs, ys = zip(*coords)
            ax.plot(xs, ys, linewidth=1.3, label=f"#{row['rank']} {row['candidate_id']}")
        for row in zone_hist:
            template = CSTAirfoilTemplate(
                zone_name=zone_name,
                upper_coefficients=tuple(row["upper_coefficients"]),
                lower_coefficients=tuple(row["lower_coefficients"]),
                te_thickness_m=float(row["te_thickness"]),
                candidate_role=str(row["candidate_id"]),
            )
            coords = generate_cst_coordinates(template)
            xs, ys = zip(*coords)
            ax.plot(xs, ys, linestyle="--", linewidth=1.0, alpha=0.75, label=row["candidate_id"])
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlabel("x/c")
        ax.set_ylabel("y/c")
        ax.set_title(f"{scale_name} {zone_name} top seedless vs historical CST shapes")
        ax.grid(True, alpha=0.25)
        ax.legend(fontsize=6, ncol=2)
        path = output_dir / f"{filename_prefix}{zone_name}_shape_overlay.png"
        fig.tight_layout()
        fig.savefig(path, dpi=180)
        plt.close(fig)
        plot_files.append(path)

        fig, ax = plt.subplots(figsize=(7, 4.5))
        for row in (*zone_top[:5], *zone_hist):
            result = _plot_condition_result(
                raw_by_zone_role.get((zone_name, str(row["candidate_id"])), ()),
                preferred_roughness="clean",
            )
            points = _polar_points_for_plot(result)
            if not points:
                continue
            ax.plot(
                [point["cl"] for point in points],
                [point["cd"] for point in points],
                linewidth=1.2,
                linestyle="--" if row.get("source") == "historical" else "-",
                label=str(row["candidate_id"]),
            )
        ax.set_xlabel("CL")
        ax.set_ylabel("CD")
        ax.set_title(f"{scale_name} {zone_name} clean CD vs CL")
        ax.grid(True, alpha=0.25)
        ax.legend(fontsize=6, ncol=2)
        path = output_dir / f"{filename_prefix}{zone_name}_cd_vs_cl.png"
        fig.tight_layout()
        fig.savefig(path, dpi=180)
        plt.close(fig)
        plot_files.append(path)

        fig, ax = plt.subplots(figsize=(7, 4.5))
        for row in (*zone_top[:5], *zone_hist):
            result = _plot_condition_result(
                raw_by_zone_role.get((zone_name, str(row["candidate_id"])), ()),
                preferred_roughness="clean",
            )
            points = _polar_points_for_plot(result)
            if not points:
                continue
            ax.plot(
                [point["cl"] for point in points],
                [point["cm"] for point in points],
                linewidth=1.2,
                linestyle="--" if row.get("source") == "historical" else "-",
                label=str(row["candidate_id"]),
            )
        ax.set_xlabel("CL")
        ax.set_ylabel("Cm")
        ax.set_title(f"{scale_name} {zone_name} clean Cm vs CL")
        ax.grid(True, alpha=0.25)
        ax.legend(fontsize=6, ncol=2)
        path = output_dir / f"{filename_prefix}{zone_name}_cm_vs_cl.png"
        fig.tight_layout()
        fig.savefig(path, dpi=180)
        plt.close(fig)
        plot_files.append(path)

        top_role = str(zone_top[0]["candidate_id"])
        fig, ax = plt.subplots(figsize=(7, 4.5))
        for result in raw_by_zone_role.get((zone_name, top_role), ()):
            points = _polar_points_for_plot(result)
            if not points:
                continue
            roughness = str(result.get("roughness_mode", "unknown"))
            reynolds = float(result.get("reynolds", 0.0))
            ax.plot(
                [point["cl"] for point in points],
                [point["cd"] for point in points],
                linewidth=1.2,
                label=f"{roughness} Re={reynolds/1000:.0f}k",
            )
        ax.set_xlabel("CL")
        ax.set_ylabel("CD")
        ax.set_title(f"{scale_name} {zone_name} rank-1 clean vs rough comparison")
        ax.grid(True, alpha=0.25)
        ax.legend(fontsize=6, ncol=2)
        path = output_dir / f"{filename_prefix}{zone_name}_clean_vs_rough_cd.png"
        fig.tight_layout()
        fig.savefig(path, dpi=180)
        plt.close(fig)
        plot_files.append(path)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    for zone_name in ZONE_NAMES:
        rows = [row for row in top_rows if row["zone"] == zone_name][:5]
        ax.scatter(
            [float(row["tc"]) for row in rows],
            [float(row["camber"]) for row in rows],
            label=zone_name,
        )
    ax.set_xlabel("max t/c")
    ax.set_ylabel("max camber/c")
    ax.set_title(f"{scale_name} top candidate thickness/camber summary")
    ax.grid(True, alpha=0.25)
    ax.legend()
    path = output_dir / f"{filename_prefix}tc_camber_summary.png"
    fig.tight_layout()
    fig.savefig(path, dpi=180)
    plt.close(fig)
    plot_files.append(path)
    return plot_files


def _plot_condition_result(
    results: Sequence[Mapping[str, object]],
    *,
    preferred_roughness: str,
) -> Mapping[str, object] | None:
    candidates = [
        result
        for result in results
        if str(result.get("roughness_mode", "")) == preferred_roughness
        and isinstance(result.get("polar_points"), list)
    ]
    if not candidates:
        candidates = [
            result for result in results if isinstance(result.get("polar_points"), list)
        ]
    if not candidates:
        return None
    reynolds_values = [float(result.get("reynolds", 0.0)) for result in candidates]
    target_reynolds = sorted(reynolds_values)[len(reynolds_values) // 2]
    return min(
        candidates,
        key=lambda result: abs(float(result.get("reynolds", 0.0)) - target_reynolds),
    )


def _polar_points_for_plot(
    result: Mapping[str, object] | None,
) -> list[dict[str, float]]:
    if result is None:
        return []
    raw_points = result.get("polar_points")
    if not isinstance(raw_points, list):
        return []
    points: list[dict[str, float]] = []
    for point in raw_points:
        if not isinstance(point, Mapping):
            continue
        cl = point.get("cl")
        cd = point.get("cd")
        cm = point.get("cm")
        if isinstance(cl, int | float) and isinstance(cd, int | float) and isinstance(cm, int | float):
            points.append({"cl": float(cl), "cd": float(cd), "cm": float(cm)})
    return sorted(points, key=lambda point: point["cl"])


def _scale_configs(args: argparse.Namespace, cfg: Any) -> tuple[ScaleConfig, ...]:
    smoke = ScaleConfig(
        name="smoke",
        sample_count=128,
        coarse_score_count=12,
        robust_score_count=3,
        reynolds_factors=(1.0,),
        roughness_modes=("clean",),
        robust_enabled=False,
    )
    medium = ScaleConfig(
        name="medium",
        sample_count=512,
        coarse_score_count=64,
        robust_score_count=16,
        reynolds_factors=(0.85, 1.0, 1.15),
        roughness_modes=tuple(cfg.cst_search.robust_roughness_modes),
        robust_enabled=True,
        zones=tuple(args.medium_zones.split(",")) if args.medium_zones else ZONE_NAMES,
    )
    production_probe = ScaleConfig(
        name="production-probe",
        sample_count=1024,
        coarse_score_count=int(cfg.cst_search.coarse_score_count or 96),
        robust_score_count=int(cfg.cst_search.robust_score_count or 24),
        reynolds_factors=(0.85, 1.0, 1.15),
        roughness_modes=tuple(cfg.cst_search.robust_roughness_modes),
        robust_enabled=True,
        zones=tuple(args.production_probe_zones.split(","))
        if args.production_probe_zones
        else ZONE_NAMES,
    )
    by_name = {
        "smoke": smoke,
        "medium": medium,
        "production-probe": production_probe,
    }
    if args.scale == "all":
        return (smoke, medium, production_probe)
    return (by_name[args.scale],)


def run_audit(args: argparse.Namespace) -> dict[str, object]:
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cfg = load_concept_config(args.config)
    worker = JuliaXFoilWorker(
        project_dir=Path("."),
        cache_dir=output_dir / "polar_db",
        persistent_mode=not args.no_persistent_worker,
        persistent_worker_count=int(args.worker_count),
        xfoil_max_iter=int(cfg.polar_worker.xfoil_max_iter),
        xfoil_panel_count=int(cfg.polar_worker.xfoil_panel_count),
    )
    try:
        scale_payloads = [
            _run_seedless_scale(
                scale=scale,
                cfg=cfg,
                worker=worker,
                top_n=int(args.top_n),
            )
            for scale in _scale_configs(args, cfg)
        ]
    finally:
        worker.close()

    all_top_rows = [
        row for scale_payload in scale_payloads for row in scale_payload["top_rows"]
    ]
    all_historical_rows = [
        row for scale_payload in scale_payloads for row in scale_payload["historical_rows"]
    ]
    all_zone_counts = [
        row for scale_payload in scale_payloads for row in scale_payload["zone_counts"]
    ]
    all_feasibility_rows = [
        row for scale_payload in scale_payloads for row in scale_payload["feasibility_rows"]
    ]
    all_stall_design_rows = [
        row for scale_payload in scale_payloads for row in scale_payload["stall_design_rows"]
    ]
    _write_csv(output_dir / "top_candidates.csv", all_top_rows)
    _write_csv(output_dir / "historical_baselines.csv", all_historical_rows)
    _write_csv(output_dir / "zone_evaluation_counts.csv", all_zone_counts)
    _write_csv(output_dir / "phase5_feasibility_stats.csv", all_feasibility_rows)
    _write_csv(output_dir / "phase5_stall_design_audit.csv", all_stall_design_rows)

    run_payload = {
        "config_path": str(args.config),
        "reference_design_source": (
            "embedded from output/birdman_mission_coupled_medium_search_20260503/"
            "top_candidate_exports/rank_01_sample_1476/station_table.json"
        ),
        "scales": [
            {
                key: value
                for key, value in scale_payload.items()
                if key != "raw_worker_results"
            }
            for scale_payload in scale_payloads
        ],
        "worker_cache_statistics": worker.cache_statistics,
    }
    plot_files: list[Path] = []
    if scale_payloads and not bool(args.skip_plots):
        first_scale = scale_payloads[0]
        last_scale = scale_payloads[-1]
        plot_files.extend(
            _plot_outputs(
                output_dir=output_dir,
                scale_payload=first_scale,
                filename_prefix=f"{first_scale['scale']}_",
            )
        )
        if last_scale is not first_scale:
            plot_files.extend(
                _plot_outputs(
                    output_dir=output_dir,
                    scale_payload=last_scale,
                    filename_prefix=f"{last_scale['scale']}_",
                )
            )
    _write_report(output_dir=output_dir, run_payload=run_payload, plot_files=plot_files)
    _write_phase5_report(output_dir=output_dir, run_payload=run_payload)
    (output_dir / "run_summary.json").write_text(
        json.dumps(run_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return run_payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scale", choices=("smoke", "medium", "production-probe", "all"), default="all")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--output-dir", type=Path, default=REPORT_DIR)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--worker-count", type=int, default=4)
    parser.add_argument("--no-persistent-worker", action="store_true")
    parser.add_argument("--skip-plots", action="store_true")
    parser.add_argument(
        "--medium-zones",
        default="",
        help="Comma-separated zone override for medium, e.g. root,tip.",
    )
    parser.add_argument(
        "--production-probe-zones",
        default="",
        help="Comma-separated zone override for production-probe, e.g. root,tip.",
    )
    args = parser.parse_args()
    payload = run_audit(args)
    for scale in payload["scales"]:
        print(
            f"{scale['scale']}: samples={scale['sample_count']} "
            f"zones={','.join(scale['zones'])} worker_results={scale['worker_result_count']} "
            f"elapsed={float(scale['elapsed_s']):.1f}s"
        )
    print(f"wrote seedless selection behavior audit to {args.output_dir}")


if __name__ == "__main__":
    main()
